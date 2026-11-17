import os, uuid, json
from datetime import datetime
from typing import List, Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()
app = FastAPI(title="Food Delivery API")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_methods=["*"], allow_headers=["*"])

MENU = [
    {"id": 1, "name": "Madurai Mutton Biryani", "price": 320, "category": "Biryani", "veg": False, "desc": "Seeraga samba rice, slow-cooked mutton"},
    {"id": 2, "name": "Veg Dum Biryani", "price": 190, "category": "Biryani", "veg": True, "desc": "Vegetables, mint, fried onions"},
    {"id": 3, "name": "Kothu Parotta", "price": 150, "category": "Tiffin", "veg": False, "desc": "Shredded parotta, egg, salna"},
    {"id": 4, "name": "Ghee Pongal", "price": 90, "category": "Tiffin", "veg": True, "desc": "Rice, moong dal, pepper, ghee"},
    {"id": 5, "name": "Masala Dosa", "price": 110, "category": "Tiffin", "veg": True, "desc": "Crisp dosa, potato masala"},
    {"id": 6, "name": "Chicken 65", "price": 210, "category": "Starters", "veg": False, "desc": "Spicy fried chicken, curry leaf"},
    {"id": 7, "name": "Paneer Butter Masala", "price": 220, "category": "Curries", "veg": True, "desc": "Creamy tomato gravy"},
    {"id": 8, "name": "Jigarthanda", "price": 120, "category": "Drinks", "veg": True, "desc": "Madurai's cold milk, almond gum, ice cream"},
]
ORDERS = {}
STATUS_FLOW = ["Placed", "Preparing", "Out for delivery", "Delivered"]


class CartItem(BaseModel):
    id: int
    qty: int


class OrderIn(BaseModel):
    items: List[CartItem]
    name: str
    phone: str
    address: str


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatIn(BaseModel):
    messages: List[ChatMessage]
    cart: List[CartItem] = []
    order_id: Optional[str] = None


@app.get("/api/menu")
def get_menu(category: Optional[str] = None, veg: Optional[bool] = None):
    items = MENU
    if category:
        items = [m for m in items if m["category"].lower() == category.lower()]
    if veg is not None:
        items = [m for m in items if m["veg"] == veg]
    return items


@app.post("/api/orders")
def create_order(body: OrderIn):
    lookup = {m["id"]: m for m in MENU}
    lines, total = [], 0
    for it in body.items:
        m = lookup.get(it.id)
        if not m or it.qty < 1:
            raise HTTPException(400, f"Invalid item {it.id}")
        lines.append({"id": m["id"], "name": m["name"], "qty": it.qty, "price": m["price"]})
        total += m["price"] * it.qty
    if not lines:
        raise HTTPException(400, "Cart is empty")
    delivery = 0 if total >= 400 else 30
    oid = uuid.uuid4().hex[:8].upper()
    ORDERS[oid] = {"id": oid, "items": lines, "subtotal": total, "delivery": delivery,
                   "total": total + delivery, "name": body.name, "phone": body.phone,
                   "address": body.address, "status": 0,
                   "created": datetime.utcnow().isoformat()}
    return public_order(ORDERS[oid])


def public_order(o):
    return {**o, "status": STATUS_FLOW[o["status"]]}


@app.get("/api/orders/{oid}")
def get_order(oid: str):
    if oid not in ORDERS:
        raise HTTPException(404, "Order not found")
    return public_order(ORDERS[oid])


@app.post("/api/orders/{oid}/advance")
def advance(oid: str):
    """Demo helper: moves the order to the next stage."""
    o = ORDERS.get(oid)
    if not o:
        raise HTTPException(404, "Order not found")
    o["status"] = min(o["status"] + 1, len(STATUS_FLOW) - 1)
    return public_order(o)


def fallback_reply(text: str) -> str:
    t = text.lower()
    if "veg" in t and "non" not in t:
        names = ", ".join(m["name"] for m in MENU if m["veg"])
        return f"Vegetarian options: {names}."
    if "cheap" in t or "budget" in t:
        m = min(MENU, key=lambda x: x["price"])
        return f"Cheapest item: {m['name']} at ₹{m['price']}."
    return "Ask me about the menu, spice level, veg options, or your order status."


@app.post("/api/assistant")
def assistant(body: ChatIn):
    last = body.messages[-1].content if body.messages else ""
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return {"reply": fallback_reply(last)}
    from anthropic import Anthropic
    client = Anthropic(api_key=key)
    order = public_order(ORDERS[body.order_id]) if body.order_id in ORDERS else None
    system = (
        "You are a friendly food delivery assistant for a Madurai restaurant app. "
        "Help users choose dishes, answer dietary questions, and explain order status. "
        "Use only the menu below. Prices are in rupees. Keep answers short (max 3 sentences). "
        "If you recommend dishes, mention exact names.\n"
        f"MENU: {json.dumps(MENU)}\nCURRENT CART: {body.cart}\nORDER: {json.dumps(order)}\n"
        "Free delivery over ₹400, otherwise ₹30."
    )
    try:
        res = client.messages.create(
            model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
            max_tokens=400, system=system,
            messages=[{"role": m.role, "content": m.content} for m in body.messages[-10:]],
        )
        return {"reply": res.content[0].text}
    except Exception:
        return {"reply": fallback_reply(last)}