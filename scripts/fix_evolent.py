import os
import sys

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models import Company, GoldenLead

def fix_evolent():
    db = SessionLocal()
    try:
        # 1. Update Evolent Health vertically to payer (it should already be but let's be safe)
        evolent_health = db.query(Company).filter(Company.name == "Evolent Health").first()
        if evolent_health:
            evolent_health.vertical = "payer"
            print("Set Evolent Health vertical to payer")
            
        # 2. Update 'Evolent' (which likely came from a scraper) to 'payer' as well
        evolent_short = db.query(Company).filter(Company.name == "Evolent").first()
        if evolent_short:
            evolent_short.vertical = "payer"
            print("Set Evolent vertical to payer")
            
        db.commit()
    finally:
        db.close()

if __name__ == "__main__":
    fix_evolent()
