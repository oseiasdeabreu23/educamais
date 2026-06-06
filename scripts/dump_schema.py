import sqlite3, json, sys

conn = sqlite3.connect('instance/migration_temp.db')
cur = conn.cursor()
cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
tables = cur.fetchall()
schema_lines = []
for name, sql in tables:
    if sql:
        schema_lines.append(sql + ';')
print('\n\n'.join(schema_lines))
conn.close()
