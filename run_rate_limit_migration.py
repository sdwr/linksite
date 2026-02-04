"""Run the rate limit migration on the database."""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(os.getenv('DATABASE_URL'))
conn.autocommit = True
cur = conn.cursor()

# Run migration
with open('migrate_rate_limits.sql', 'r') as f:
    sql = f.read()

# Split by semicolons and execute each statement
for stmt in sql.split(';'):
    stmt = stmt.strip()
    if stmt and not stmt.startswith('--'):
        print(f'Executing: {stmt[:60]}...')
        try:
            cur.execute(stmt)
            print('  OK')
        except Exception as e:
            print(f'  Error: {e}')

cur.close()
conn.close()
print('Migration complete!')
