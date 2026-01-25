#!/usr/bin/env python3
"""
Migration: Add V2 pipeline columns to proactive_outreach table
"""
import sqlalchemy as sa
from database import engine

def migrate_add_v2_columns():
    """Add V2 pipeline columns to proactive_outreach table"""
    
    with engine.begin() as conn:
        inspector = sa.inspect(engine)
        existing_columns = [col['name'] for col in inspector.get_columns('proactive_outreach')]
        
        new_columns = [
            ('ds_wedge', 'VARCHAR'),
            ('ds_rationale', 'TEXT'),
            ('ds_key_points', 'JSON'),
            ('ds_raw_draft', 'TEXT'),
            ('px_final_email', 'TEXT'),
            ('px_factual_flags', 'JSON'),
            ('px_confidence', 'NUMERIC'),
            ('px_citations', 'JSON')
        ]
        
        added = []
        skipped = []
        
        for col_name, col_type in new_columns:
            if col_name not in existing_columns:
                try:
                    conn.execute(sa.text(f'ALTER TABLE proactive_outreach ADD COLUMN {col_name} {col_type}'))
                    added.append(col_name)
                    print(f'✅ Added column: {col_name}')
                except Exception as e:
                    print(f'❌ Failed to add {col_name}: {e}')
            else:
                skipped.append(col_name)
                print(f'✓ Column {col_name} already exists')
        
        print(f'\n{"="*60}')
        print(f'Migration complete!')
        print(f'Added: {len(added)} columns')
        print(f'Skipped (already exist): {len(skipped)} columns')
        print(f'{"="*60}')
        
        if added:
            print(f'\n✅ Successfully added: {", ".join(added)}')
        if skipped:
            print(f'ℹ️  Already present: {", ".join(skipped)}')

if __name__ == "__main__":
    migrate_add_v2_columns()
