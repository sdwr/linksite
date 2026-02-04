#!/usr/bin/env python3
"""Run the admin dashboard improvements migration."""

from db import execute

print('Running admin dashboard improvements migration...')

# 1. Add reddit_api_stats column
try:
    execute('ALTER TABLE global_state ADD COLUMN IF NOT EXISTS reddit_api_stats JSONB DEFAULT %s::jsonb', ('{}',))
    print('1. Added reddit_api_stats column to global_state')
except Exception as e:
    print(f'1. reddit_api_stats: {e}')

# 2. Add links_processed column
try:
    execute('ALTER TABLE job_runs ADD COLUMN IF NOT EXISTS links_processed JSONB DEFAULT %s::jsonb', ('[]',))
    print('2. Added links_processed column to job_runs')
except Exception as e:
    print(f'2. links_processed: {e}')

# 3. Add index
try:
    execute('CREATE INDEX IF NOT EXISTS idx_job_runs_type_status ON job_runs(job_type, status)')
    print('3. Added index idx_job_runs_type_status')
except Exception as e:
    print(f'3. index: {e}')

# 4. Set default for started_at
try:
    execute('ALTER TABLE job_runs ALTER COLUMN started_at SET DEFAULT NOW()')
    print('4. Set started_at default to NOW()')
except Exception as e:
    print(f'4. started_at: {e}')

print('Migration complete!')
