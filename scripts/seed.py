import json
import sys
import uuid
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.db import SessionLocal, engine
from app.models import Base, Contract, Shipment
from app.services.document_service import ContractService

DATA_DIR = Path(__file__).parent.parent / "data"


def seed():
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        contract_service = ContractService(db)
        contracts_dir = DATA_DIR / "contracts"
        contracts_loaded = 0

        print(f"Loading contracts from {contracts_dir} ...")
        for contract_file in sorted(contracts_dir.glob("*.txt")):
            n = contract_service.load_contract_file(contract_file)
            contracts_loaded += n
            status = "loaded" if n else "skipped (already exists)"
            print(f"  {contract_file.name}: {status}")

        shipments_file = DATA_DIR / "shipments.json"
        shipments_loaded = 0
        print(f"\nLoading shipments from {shipments_file} ...")
        with open(shipments_file, "r") as f:
            shipments = json.load(f)

        for s in shipments:
            existing = db.query(Shipment).filter(Shipment.tracking_id == s["tracking_id"]).first()
            if existing:
                print(f"  {s['tracking_id']}: skipped (already exists)")
                continue
            ship = Shipment(
                id=str(uuid.uuid4()),
                tracking_id=s["tracking_id"],
                carrier_id=s["carrier_id"],
                origin=s["origin"],
                destination=s["destination"],
                weight_kg=float(s["weight_kg"]),
                service_type=s["service_type"],
                zone=int(s["zone"]),
                ship_date=date.fromisoformat(s["ship_date"]),
                delivered_date=date.fromisoformat(s["delivered_date"]) if s.get("delivered_date") else None,
                created_at=datetime.utcnow(),
            )
            db.add(ship)
            shipments_loaded += 1
            print(f"  {s['tracking_id']}: loaded")

        db.commit()
        print(f"\n✓ Seed complete: {contracts_loaded} contract(s), {shipments_loaded} shipment(s) loaded.")

    except Exception as e:
        db.rollback()
        print(f"✗ Seed failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
