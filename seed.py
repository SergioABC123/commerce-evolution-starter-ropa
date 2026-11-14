"""Seed catalog for Trendify, the team's clothing storefront.

The starter only inserts products into an empty database. For an existing
local development database, run `python reset_db.py` before this script.
Warning: reset_db.py removes prior development orders as well.
"""

from sqlalchemy import func, select

from store import create_app
from store.db import get_session
from store.models import Product

# (sku, name, description, price_cents, stock_quantity, image_url)
PRODUCTS = [
    ('TRND-001', 'Oversized Tee - Bone', 'Heavyweight cotton t-shirt with a relaxed silhouette, dropped shoulders, and a soft bone finish.', 39900, 12, '/static/images/oversized-tee-bone.svg'),
    ('TRND-002', 'Essential Hoodie - Graphite', 'Everyday fleece hoodie featuring a roomy fit, adjustable drawstrings, and a front kangaroo pocket.', 89900, 8, '/static/images/essential-hoodie-graphite.svg'),
    ('TRND-003', 'Cargo Pants - Asphalt', 'Relaxed utility trousers with functional side pockets and an adjustable streetwear fit.', 79900, 10, '/static/images/cargo-pants-asphalt.svg'),
    ('TRND-004', 'Denim Jacket - Indigo', 'Classic indigo denim jacket with structured seams, metal-look buttons, and a versatile boxy cut.', 99900, 7, '/static/images/denim-jacket-indigo.svg'),
    ('TRND-005', 'Cropped Puffer - Stone', 'Lightweight quilted puffer jacket with a cropped silhouette, high collar, and warm insulation.', 129900, 6, '/static/images/cropped-puffer-stone.svg'),
    ('TRND-006', 'Knit Sweater - Oat', 'Soft textured crewneck sweater in a neutral oat tone, designed for effortless layering.', 69900, 11, '/static/images/knit-sweater-oat.svg'),
    ('TRND-007', 'Pleated Skirt - Noir', 'High-waisted black pleated skirt with a fluid shape and a clean minimalist finish.', 59900, 9, '/static/images/pleated-skirt-noir.svg'),
    ('TRND-008', 'Crossbody Bag - Onyx', 'Compact crossbody bag with a secure zip closure, adjustable strap, and everyday storage.', 44900, 15, '/static/images/crossbody-bag-onyx.svg'),
]


def seed() -> None:
    app = create_app()
    with app.app_context():
        db = get_session()
        count = db.scalar(select(func.count()).select_from(Product))
        if count:
            print(f"Database already contains {count} products; nothing changed.")
            return

        for sku, name, description, price, stock, image_url in PRODUCTS:
            db.add(Product(
                sku=sku,
                name=name,
                description=description,
                price_cents=price,
                stock_quantity=stock,
                image_url=image_url,
                active=1,
            ))
        db.commit()
        print(f"Seeded {len(PRODUCTS)} Trendify products.")


if __name__ == "__main__":
    seed()
