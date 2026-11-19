import json
import uuid
from datetime import date, datetime
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Contract, Shipment
from app.response import success_response
from app.services.document_service import ContractService

log = structlog.get_logger()
router = APIRouter(prefix="/admin", tags=["Admin"])

DATA_DIR = Path(__file__).parent.parent.parent / "data"


@router.post("/seed")
def seed_database(db: Session = Depends(get_db)):
    contracts_loaded = 0
    shipments_loaded = 0

    contract_service = ContractService(db)
    contracts_dir = DATA_DIR / "contracts"
    for contract_file in sorted(contracts_dir.glob("*.txt")):
        result = contract_service.load_contract_file(contract_file)
        contracts_loaded += result

    shipments_file = DATA_DIR / "shipments.json"
    if shipments_file.exists():
        with open(shipments_file, "r") as f:
            shipments = json.load(f)
        for s in shipments:
            existing = db.query(Shipment).filter(Shipment.tracking_id == s["tracking_id"]).first()
            if not existing:
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
        db.commit()

    log.info("seed_complete", contracts_loaded=contracts_loaded, shipments_loaded=shipments_loaded)
    return success_response(
        data={"contracts_loaded": contracts_loaded, "shipments_loaded": shipments_loaded},
        message=f"Seeded {contracts_loaded} contract(s) and {shipments_loaded} shipment(s)",
    )
