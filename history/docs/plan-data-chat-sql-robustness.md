# Plan: Data Chat SQL Robustness

**Ziel:** SQL-Fehler (insbesondere fehlende `GROUP BY`-Klauseln auf bereits aggregierten Views) eliminieren, damit User in Cowork und im Dashboard keine kryptischen BQ-Fehler sehen.

**Scope:** Zwei Fixes, kombiniert in einem PR — präventiv (Prompt) + defensiv (Retry).

---

## Hintergrund

Wiederholt beobachtet: Claude generiert SQL der Form

```sql
SELECT date, SUM(cost), SUM(sales) FROM v_ads_summary_daily WHERE … ORDER BY date
```

ohne `GROUP BY date`. BigQuery wirft daraufhin einen 400-Fehler. Die Views sind bereits auf Tagesgranularität aggregiert (eine Zeile pro Tag), also wäre `SELECT date, cost, sales` ohne SUM korrekt.

Das Problem ist nicht auf `GROUP BY` beschränkt — auch andere SQL-Fehlerklassen (Tippfehler in Spaltennamen, falsche JOIN-Keys, fehlende SAFE_DIVIDE) können zu BQ-400-Fehlern führen. Die beiden Fixes adressieren das auf zwei Ebenen:

1. **Fix 1 (Prävention):** Schema-Kontext in `data_catalog.yaml` schärfen → Claude bekommt die Information direkt im Prompt.
2. **Fix 2 (Defense-in-Depth):** SQL-Retry-Schleife im Service-Layer → bei BQ-400 wird der Fehler als Correction-Turn an Claude zurückgespielt und SQL neu generiert (max. 1 Retry).

Fix 2 ist die robustere Lösung; Fix 1 reduziert die Rate der Erstfehler und damit die Anzahl der Retries.

---

## Fix 1: Schema-Kontext in `data_catalog.yaml`

### Was ändern

Für alle `v_*_daily`-Views ein explizites `important`-Feld hinzufügen, das Claude über die Granularität informiert. Das Feld wird bereits von `data_chat_schema.py:_format_view()` mit `**Important:**`-Präfix in den System-Prompt gerendert.

**Views betroffen:**
- `v_ads_summary_daily` — eine Zeile pro Client pro Tag
- `v_ads_campaign_daily` — eine Zeile pro Campaign pro Tag
- `v_ads_adgroup_daily` — eine Zeile pro Ad Group pro Tag
- `v_ads_asin_daily` — eine Zeile pro ASIN pro Campaign pro Tag
- `v_ads_searchterm_daily` — eine Zeile pro Search Term pro Campaign pro Ad Group pro Tag
- `pma_sales_traffic_daily` — eine Zeile pro Tag pro Marktplatz
- `pma_sales_traffic_by_child_asin` — eine Zeile pro ASIN pro Tag

### Formulierung für `important`-Felder

Alle daily Views:
```
Already aggregated at the daily grain — one row per [dimension] per day.
Do NOT wrap metrics in SUM() unless you are aggregating across multiple dimension
values (e.g., summing campaigns into a client total). For time-series queries
(SELECT date, metric ORDER BY date), use the column directly without SUM().
Always recalculate ratio KPIs (acos, roas, ctr, cpc) from summed components —
never average them across rows.
```

Zusätzlich in `ai_warnings` im Catalog-Root:
```
- Views named v_*_daily and pma_*_daily are pre-aggregated. Direct column access
  (no SUM) is correct for time-series queries. Use SUM only when collapsing
  across a non-date dimension (e.g., summing all campaigns into a client total).
```

### Betroffene Dateien

- `config/data_catalog.yaml` — `important`-Felder für alle daily Views + `ai_warnings`-Eintrag

---

## Fix 2: SQL-Retry-Schleife

### Wo

`src/adp/services/data_chat.py` — betrifft beide Konsumenten (Dashboard + MCP) gleichzeitig.

### Mechanismus

Wenn `execute_query()` mit einem BQ-400-Fehler fehlschlägt, wird die Fehlermeldung als Correction-Turn an `generate_sql()` zurückgespielt. Claude sieht dann:

```
[User]      → Originale Frage
[Assistant] → Fehlerhaftes SQL
[User]      → "The previous query failed with: <BQ error message>. Please fix the SQL."
[Assistant] → Korrigiertes SQL  ← Retry-Ergebnis
```

Max. 1 Retry. Kein Retry bei anderen Fehlerklassen (Netzwerk, Timeout, etc.) — nur `google.api_core.exceptions.BadRequest`.

### API-Änderung: `generate_sql()`

```python
def generate_sql(
    question: str,
    dataset: str,
    gcp_project: str,
    start_date: date,
    end_date: date,
    history: list[dict] | None = None,
    previous_sql: str | None = None,   # NEU: fehlgeschlagenes SQL für Retry
    bq_error: str | None = None,       # NEU: BQ-Fehlermeldung für Retry
) -> str:
```

Im Messages-Building am Ende einfügen, wenn `previous_sql` und `bq_error` gesetzt:
```python
if previous_sql and bq_error:
    messages.append({"role": "assistant", "content": previous_sql})
    messages.append({
        "role": "user",
        "content": f"The previous query failed with this BigQuery error:\n{bq_error}\n\nPlease fix the SQL.",
    })
```

### Änderung in `run_query()`

```python
# Nach dem ersten execute_query-Fehler:
from google.api_core.exceptions import BadRequest

try:
    df, job_id = execute_query(sql, gcp_project)
except BadRequest as e:
    # BQ-400: Retry mit Fehlermeldung als Correction-Turn
    logger.warning("bq_query_failed_retrying client=%s error=%s", client_id, str(e)[:200])
    try:
        sql = generate_sql(
            question, dataset, gcp_project, sd, ed,
            history=sql_history,
            previous_sql=sql,
            bq_error=str(e),
        )
    except Exception as gen_err:
        return {"error": f"SQL retry generation failed: {gen_err}", "sql": sql}

    valid, reason = validate_sql(sql)
    if not valid:
        return {"error": f"Invalid SQL after retry: {reason}", "sql": sql}
    if "LIMIT" not in sql.upper():
        sql = sql.rstrip(";") + " LIMIT 1000"

    try:
        df, job_id = execute_query(sql, gcp_project)
    except Exception as e2:
        logger.exception("bq_query_failed_after_retry client=%s", client_id)
        return {"error": f"Query failed after retry: {e2}", "sql": sql}

except Exception as e:
    # Andere Fehler (Netzwerk, Timeout, etc.) — kein Retry
    logger.exception("bq_query_failed client=%s", client_id)
    return {"error": f"Query failed: {e}", "sql": sql}
```

### Logging

Zwei neue Log-Events:
- `bq_query_failed_retrying` — bei 400-Fehler, vor Retry
- `bq_query_failed_after_retry` — wenn auch Retry fehlschlägt

Damit lässt sich in Cloud Logging messen, wie oft Retries nötig sind und ob sie helfen.

### Betroffene Dateien

- `src/adp/services/data_chat.py` — `generate_sql()` + `run_query()`

---

## Nicht im Scope

- Retry bei Interpretation-Phase (kein SQL-Fehler möglich)
- Retry-Limit > 1 (ein Retry reicht für die meisten Fälle; mehr würde Latenz und Kosten erhöhen)
- Anpassung des Dashboards (die Streamlit-Seite ruft `run_query()` auf — Fix wirkt automatisch)

---

## Aufwand

| Fix | Aufwand |
|-----|---------|
| Fix 1: `data_catalog.yaml` Annotations | ~30 Min |
| Fix 2: Retry-Schleife in `data_chat.py` | ~2–3 h inkl. Tests |
| **Gesamt** | **~3–4 h** |

---

## Testplan

**Fix 1:**
- Visuell prüfen: `build_client_schema()` in Python aufrufen und prüfen, dass `**Important:**`-Zeilen für alle daily Views im Output erscheinen.

**Fix 2:**
- Unit-Test: `generate_sql()` mit `previous_sql` + `bq_error` aufrufen — prüfen, dass der Correction-Turn in den Messages ist (Mock Anthropic Client).
- Unit-Test: `run_query()` mocken, sodass erster `execute_query`-Call `BadRequest` wirft, zweiter erfolgreicht — prüfen, dass Retry ausgelöst und `bq_query_failed_retrying` geloggt wird.
- Integrationstest: Gegen echten Client testen mit Frage die historisch `GROUP BY`-Fehler verursacht hat (z.B. „tägliche Performance der letzten 14 Tage" auf `v_ads_summary_daily`).
