from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch

from .agentic.nodes.human_review import human_review_node
from .agentic.nodes.repair import repair_node
from .agentic.nodes.validate import validate_node


VALID_DRAFT = {
    "store": {"name": "Coffee Home", "description": "Specialty coffee."},
    "store_settings": {
        "currency": "SAR",
        "language": "ar",
        "timezone": "UTC",
    },
    "theme": {
        "theme_template": "Minimal",
        "primary_color": "#112233",
        "secondary_color": "#445566",
        "font_family": "Cairo",
        "logo_url": "",
        "banner_url": "",
    },
    "categories": [
        {"name": "Coffee"},
        {"name": "Tools"},
    ],
    "products": [
        {
            "name": "Beans",
            "description": "Fresh beans",
            "price": 30,
            "sku": "B-1",
            "category_name": "Coffee",
            "stock_quantity": 5,
            "image_url": "",
        },
        {
            "name": "Dripper",
            "description": "Coffee dripper",
            "price": 50,
            "sku": "D-1",
            "category_name": "Tools",
            "stock_quantity": 3,
            "image_url": "",
        },
    ],
    "ai_analysis": (
        "The AI understood the specialty coffee store and generated "
        "a consistent catalog, theme, and store configuration."
    ),
    "clarification_needed": False,
    "clarification_questions": [],
}