"""Relatório em Markdown com os números do README, calculados a partir da BD.

Correção do enviesamento de janela: uma hora planeada H só entra nas análises por
hora se a recolha esteve ativa, sem falhas, de H − 30 min a H + 90 min. Caso
contrário, nas pontas da janela só aparecem as viagens mais atrasadas (ou mais
adiantadas), porque as outras ainda não chegaram (ou já tinham passado).
"""

from __future__ import annotations

import psycopg

COVERAGE = """
WITH mins AS (            -- minutos em que o coletor gravou posições
    SELECT DISTINCT date_trunc('minute', collected_at) AS m FROM vehicle_positions
), hours AS (
    SELECT DISTINCT time_bucket('1 hour', scheduled_at) AS h FROM stop_arrivals
)
SELECT h FROM hours
WHERE (SELECT count(*) FROM mins
       WHERE m >= h - interval '30 minutes' AND m < h + interval '90 minutes') >= 115
"""


def _table(cur: psycopg.Cursor, sql: str, params=()) -> str:
    cur.execute(sql, params)
    cols = [c.name for c in cur.description]
    rows = cur.fetchall()
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        out.append("| " + " | ".join("—" if v is None else str(v) for v in r) + " |")
    return "\n".join(out)


def build(database_url: str, tz: str = "Europe/Lisbon") -> str:
    parts: list[str] = []
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(f"CREATE TEMP TABLE covered AS {COVERAGE}")

        parts.append("### Janelas de recolha\n")
        parts.append(
            _table(
                cur,
                """
            WITH m AS (SELECT DISTINCT date_trunc('minute', collected_at) AS m
                       FROM vehicle_positions),
            g AS (SELECT m, CASE WHEN m - lag(m) OVER (ORDER BY m) > interval '5 minutes'
                                 OR lag(m) OVER (ORDER BY m) IS NULL THEN 1 ELSE 0 END AS nova
                  FROM m),
            s AS (SELECT m, sum(nova) OVER (ORDER BY m) AS janela FROM g)
            SELECT janela,
                   to_char(min(m) AT TIME ZONE %(tz)s, 'YYYY-MM-DD HH24:MI') AS inicio,
                   to_char(max(m) AT TIME ZONE %(tz)s, 'HH24:MI') AS fim,
                   round(extract(epoch FROM max(m) - min(m)) / 3600, 1) AS horas
            FROM s GROUP BY janela ORDER BY janela""",
                {"tz": tz},
            )
        )

        parts.append("\n\n### Volume por hora (posições novas após dedup)\n")
        parts.append(
            _table(
                cur,
                """
            SELECT to_char(time_bucket('1 hour', ts) AT TIME ZONE %(tz)s, 'DD/MM HH24"h"') AS hora,
                   count(DISTINCT vehicle_id) AS veiculos,
                   count(*) AS posicoes,
                   count(DISTINCT date_trunc('minute', collected_at)) AS minutos_recolha,
                   round(count(*) / (60.0 * count(DISTINCT date_trunc('minute', collected_at))), 1)
                       AS eventos_por_s
            FROM vehicle_positions GROUP BY time_bucket('1 hour', ts) ORDER BY 1""",
                {"tz": tz},
            )
        )

        parts.append("\n\n### Atraso por hora planeada (só horas com cobertura completa)\n")
        parts.append(
            _table(
                cur,
                """
            SELECT to_char(a.h AT TIME ZONE %(tz)s, 'DD/MM HH24"h"') AS hora_planeada,
                   count(*) AS chegadas,
                   round(avg(s.delay_s) / 60.0, 1) AS media_min,
                   round((percentile_cont(0.5) WITHIN GROUP (ORDER BY s.delay_s) / 60.0)::numeric, 1)
                       AS p50_min,
                   round((percentile_cont(0.9) WITHIN GROUP (ORDER BY s.delay_s) / 60.0)::numeric, 1)
                       AS p90_min,
                   round(100.0 * avg((s.delay_s BETWEEN -60 AND 300)::int), 1) AS pct_pontual
            FROM covered a JOIN stop_arrivals s ON time_bucket('1 hour', s.scheduled_at) = a.h
            WHERE s.uncertainty_s <= 60
            GROUP BY a.h ORDER BY a.h""",
                {"tz": tz},
            )
        )

        parts.append("\n\n### Métodos de deteção\n")
        parts.append(
            _table(
                cur,
                """
            SELECT method AS metodo, count(*) AS chegadas,
                   round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct,
                   round(avg(uncertainty_s)::numeric, 1) AS incerteza_media_s,
                   round((percentile_cont(0.5) WITHIN GROUP (ORDER BY delay_s) / 60.0)::numeric, 1)
                       AS p50_atraso_min
            FROM stop_arrivals GROUP BY method ORDER BY 2 DESC""",
            )
        )

        parts.append(
            "\n\n### Linhas com mais atraso (≥ 200 chegadas, horas com cobertura completa)\n"
        )
        parts.append(
            _table(
                cur,
                """
            SELECT s.line_id AS linha, count(*) AS chegadas,
                   round(avg(s.delay_s) / 60.0, 1) AS media_min,
                   round(100.0 * avg((s.delay_s BETWEEN -60 AND 300)::int), 1) AS pct_pontual
            FROM stop_arrivals s JOIN covered a ON time_bucket('1 hour', s.scheduled_at) = a.h
            WHERE s.uncertainty_s <= 60
            GROUP BY s.line_id HAVING count(*) >= 200 ORDER BY media_min DESC LIMIT 10""",
            )
        )

        parts.append(
            "\n\n### Linhas mais pontuais (≥ 200 chegadas, horas com cobertura completa)\n"
        )
        parts.append(
            _table(
                cur,
                """
            SELECT s.line_id AS linha, count(*) AS chegadas,
                   round(avg(s.delay_s) / 60.0, 1) AS media_min,
                   round(100.0 * avg((s.delay_s BETWEEN -60 AND 300)::int), 1) AS pct_pontual
            FROM stop_arrivals s JOIN covered a ON time_bucket('1 hour', s.scheduled_at) = a.h
            WHERE s.uncertainty_s <= 60
            GROUP BY s.line_id HAVING count(*) >= 200 ORDER BY pct_pontual DESC LIMIT 10""",
            )
        )

        parts.append("\n\n### Totais\n")
        parts.append(
            _table(
                cur,
                """
            SELECT (SELECT count(*) FROM vehicle_positions) AS posicoes,
                   (SELECT count(DISTINCT vehicle_id) FROM vehicle_positions) AS veiculos,
                   (SELECT count(*) FROM stop_arrivals) AS chegadas,
                   (SELECT count(DISTINCT trip_id) FROM stop_arrivals) AS viagens,
                   (SELECT count(DISTINCT line_id) FROM stop_arrivals) AS linhas,
                   (SELECT pg_size_pretty(hypertable_size('vehicle_positions'))) AS espaco_posicoes""",
            )
        )
    return "\n".join(parts) + "\n"
