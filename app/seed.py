"""First-run data: the five kitchens and their current menus.

Transcribed from zaria-court-menus.html. After the first run this file stops
mattering — vendors edit their own menus from the console, which is the whole
point of the exercise.
"""
from __future__ import annotations

from . import config, db, security

# (slug, name, kind, tagline, accent, logo, momo, phone, external_url, accepts_orders)
VENDORS = [
    ("mr-chips", "Mr Chips", "Fast food and takeaway",
     "Crispy, golden perfection in every bite. A local favourite, reimagined.",
     "#ED1C24", "vendor-chips.png", "7700777", "", "", 1),
    ("food-and-stuff", "Food & Stuff", "Sandwiches and catering",
     "Raising the bar for culinary excellence. Top tier dining, made in Rwanda.",
     "#2B7333", "vendor-stuff.png", "", "", "", 1),
    ("laza", "Laza", "Ice cream and cold drinks",
     "Hand crafted ice lollies and real fruit refreshers, made right here in Kigali.",
     "#E4032B", "vendor-laza.png", "", "0795579916", "", 1),
    ("wok-spot", "Wok Spot", "Asian kitchen and cocktails",
     "Sushi, Asian plates and signature cocktails, curated by Atelier du Vin.",
     "#C9A063", "vendor-wok.jpg", "", "", "", 1),
    ("kivu-noir", "Kivu Noir", "Coffee and specialty drinks",
     "Rwandan Bourbon Arabica, hand-brewed to order. Espresso, specialty lattes and pastries.",
     "#8A5A20", "", "", "", "https://www.kivunoir.rw/menu/zaria", 0),
]

# slug -> [(category, note, [(name, price, description, tags), ...]), ...]
MENUS = {
    "mr-chips": [
        ("Chips", "Dips: chip sauce, garlic mayo, pili pili mayo, ranch, ketchup, mayo", [
            ("Regular", 3000, "", ""),
            ("Large", 4500, "", ""),
        ]),
        ("Chick'n Chips", "Dips: chicken dippin' sauce, ranch sauce", [
            ("Nuggets and chips (6 pcs)", 8500, "", ""),
            ("Strips and chips (3 pcs)", 8500, "", ""),
            ("Chicken wings (5 pcs)", 8500, "", ""),
        ]),
        ("Mr Chicken Burgers", "Original or Firebird Pili Pili. Special sauce, coleslaw and tomatoes", [
            ("Mr Crispy Chicken Burger", 8500, "", ""),
            ("Mr Grilled Chicken Burger", 8500, "", ""),
        ]),
        ("Mr Wraps and Chips", "Original or Firebird Pili Pili. Lettuce, tomato, onions, tzatziki sauce", [
            ("Mr Crispy Chicken Wrap", 8500, "", ""),
            ("Mr Grilled Chicken Wrap", 8500, "", ""),
        ]),
        ("Mr Burgers and Chips", "Ketchup, onions, tomatoes and pickles", [
            ("Beef Burger", 8000, "", ""),
            ("Double Beef Burger", 10000, "", ""),
            ("Cheese Burger", 8500, "", ""),
            ("Double Cheese Burger", 11000, "", ""),
            ("Mr Big", 8500, "Special sauce, lettuce, cheese, pickles and onions", ""),
            ("Beef hotdog and chips", 7500, "", ""),
        ]),
        ("Veg Option", "", [
            ("Falafel Burger", 7500, "", "vegetarian"),
            ("Falafel balls and chips", 7000, "", "vegetarian"),
        ]),
        ("Salads", "", [
            ("Coleslaw Regular", 2500, "", ""),
            ("Coleslaw Large", 4500, "", ""),
        ]),
        ("Drinks", "", [
            ("S. Mutzig", 2500, "", ""), ("Amstel", 2500, "", ""),
            ("Heineken", 3000, "", ""), ("Heineken Zero", 3000, "", ""),
            ("Skol Malt", 2500, "", ""), ("Skol Lager", 2500, "", ""),
            ("Virunga Mist", 2500, "", ""), ("Virunga Gold", 2500, "", ""),
            ("Virunga Silver", 2500, "", ""), ("Panache", 2000, "", ""),
            ("Bavaria", 5000, "", ""), ("Fanta plastic", 2000, "", ""),
            ("Juice Inyange", 2000, "", ""), ("Water", 1500, "", ""),
            ("Energy drink", 1500, "", ""), ("Smirnoff Ice", 5000, "", ""),
            ("Smirnoff Guarana", 5000, "", ""), ("Pablo Gin and Tonic", 5000, "", ""),
            ("Desperado", 5000, "", ""), ("Kiki", 5000, "", ""),
            ("Red Bull", 5000, "", ""),
        ]),
    ],
    "food-and-stuff": [
        ("Specialty Sandwiches",
         "Served with french fries or a side salad. Extra fries 3,500", [
            ("Artisanal Grilled Steak", 13000,
             "Marinated beef filet, melted mozzarella, roasted red pepper mayo and chimichurri on ciabatta", ""),
            ("Basil Pesto Chicken Pita", 10000,
             "Basil pesto chicken and melted mozzarella in a toasted pita pocket", ""),
            ("Coffee BBQ Pulled Pork", 9000,
             "Pulled pork slow-cooked in a coffee rub and BBQ sauce, with pickles on a sesame seed bun", ""),
            ("The Falafel Fix", 9000,
             "Handmade falafel with coconut tzatziki and tahini in a flatbread wrap or pita pocket", "vegan"),
            ("The Artisanal Chicken Club", 11500,
             "Grilled chicken, crispy bacon, avocado onion chutney on ciabatta with garlic mayo and rocket", ""),
            ("The Vital Veggie", 8000,
             "Avocado, tomato, lettuce and mozzarella in a tortilla with caramelised red onion chutney", "vegetarian"),
        ]),
        ("Fresh Salads", "Add grilled chicken breast, falafel or feta crumble for 2,500", [
            ("Green Glow Superfood Bowl", 9000,
             "Herbed quinoa, pumpkin seed, avocado and apple with cucumber and tomato on kale and rocket", "vegetarian"),
            ("Mango & Cashew Sunshine Bowl", 9000,
             "Mango salsa, roasted cashew and bulgar wheat with cucumber and tomato on kale and rocket", "vegetarian"),
        ]),
        ("Just for Kids", "Lunch Box = 1 main + 2 sides + 1 drink + 1 treat", [
            ("Kids Lunch Box", 10000,
             "Choose a main, two sides, a drink and a treat at the counter", ""),
            ("Mac & Cheese Bites", 6500, "Fried bites of gooey macaroni and cheese", "vegetarian"),
            ("Popcorn Chicken", 8500, "Coconut-crumbed crispy chicken bites", ""),
            ("Mini Pizza", 7500, "Mini pepperoni or margherita pizza", ""),
            ("Crispy Quesadilla", 8500, "Cheesy marinara or chicken and mozzarella", ""),
            ("Fish Fingers", 8500, "Crispy breaded fish fingers", ""),
            ("Spaghetti Bowl", 7500, "Spaghetti marinara or spaghetti and meatballs", ""),
        ]),
        ("Loaded Fries", "A full serving of french fries loaded with your choice of toppings", [
            ("Basil Pesto Chicken", 9500,
             "Chicken with basil pesto, green peppers and grilled mozzarella on fries", ""),
            ("BBQ Pulled Pork", 8500, "Slow cooked pulled pork with mozzarella", ""),
            ("Mozzarella", 6000, "Melted mozzarella cheese", "vegetarian"),
            ("BBQ Pulled Chicken", 9500,
             "Shredded chicken in home made BBQ sauce with mozzarella on fries", ""),
        ]),
    ],
    "laza": [
        ("Ice Cream & Treats", "", [
            ("Ice Lolly", 2500, "Dairy free", "vegan"),
            ("Ice Cream in a Cup", 4000, "Dairy", ""),
            ("Ice Cream in a Cone", 5000, "Dairy", ""),
            ("Popcorn", 2500, "Variety of flavours", "vegetarian"),
            ("Popcorn Fresh", 2000, "", "vegetarian"),
            ("Dehydrated Fruit", 1500, "", "vegan"),
        ]),
        ("Cold Drinks", "", [
            ("Hibiscus", 3000, "", "vegan"),
            ("Lemonana", 3000, "", "vegan"),
            ("Water", 1500, "", ""),
            ("Sparkling Water", 1500, "", ""),
            ("Soda", 2000, "", ""),
            ("Juice", 2000, "", ""),
            ("Juice Box", 1000, "", ""),
        ]),
        ("Hot Drinks", "", [
            ("Hot Ginger Tea", 2500, "", "vegan"),
            ("Hot Hibiscus Tea", 2500, "", "vegan"),
        ]),
    ],
    "wok-spot": [
        ("Starters", "", [
            ("Vegetable Spring Rolls", 3000, "", "vegetarian"),
            ("Chicken Spring Rolls", 5000, "", ""),
            ("French Fries", 3000, "Served with ketchup or mayonnaise", "vegetarian"),
        ]),
        ("Sushi", "", [
            ("Alaska Roll", 12000, "Smoked salmon, avocado, cucumber, nori and sesame", "chef"),
            ("California Roll", 10000, "Crab sticks, avocado, cucumber, nori and sesame", ""),
            ("Veggie Roll", 8000, "Avocado, cucumber and mango wrapped in nori", "vegetarian"),
        ]),
        ("Rice Specialties", "", [
            ("Shanghai Fried Rice (Chicken)", 8000, "", ""),
            ("Shanghai Fried Rice (Beef)", 8000, "", ""),
            ("Shanghai Fried Rice (Vegetable)", 5000, "", "vegetarian"),
        ]),
        ("Noodles", "", [
            ("Stir Fried Chicken Noodles", 15000, "Topped with fried egg", ""),
            ("Stir Fried Vegetable Noodles", 12000, "Topped with fried egg", "vegetarian"),
        ]),
        ("Main Courses", "", [
            ("Chicken Manchurian", 15000, "Served with rice or fries", "chef"),
            ("Skirt Steak", 15000, "Served with fries and seasonal vegetables", "chef"),
            ("Chicken Wings (6 pcs)", 8000, "Served with french fries", ""),
            ("Beef Wrap", 13000, "Served with french fries", ""),
            ("Tuna Wrap", 13000, "Served with french fries", ""),
            ("Chicken Wrap", 12000, "Served with french fries", ""),
        ]),
        ("Signature Cocktails", "", [
            ("Long Island Iced Tea", 12000, "Gin, rum, vodka, tequila, triple sec, coke", ""),
            ("Gin & Tonic", 10000, "Double gin plus a splash of tonic", ""),
            ("Cuba Libre", 10000, "Rum, lemon, coke", ""),
            ("Classic Mojito", 10000, "Rum, lemon, mint, sugar syrup, sparkling water", ""),
        ]),
        ("Mocktails", "", [
            ("Virgin Mojito", 8000, "", "vegan"),
            ("Lemonade", 8000, "", "vegan"),
        ]),
        ("Beers & Cider", "", [
            ("Heineken", 3000, "", ""), ("Virunga Mist", 3000, "", ""),
            ("Mützig", 2500, "", ""), ("Amstel", 2500, "", ""),
            ("Savanna Cider", 5000, "", ""), ("Smirnoff Guarana", 5000, "", ""),
        ]),
        ("Soft Drinks", "", [
            ("Soda (300 ml)", 1500,
             "Coca Cola, Sprite, Fanta Orange, Fanta Citron, Fanta Pineapple, Tonic, Coke Zero", ""),
            ("Mineral Water (500 ml)", 1500, "", ""),
            ("Red Bull Energy Drink", 5000, "", ""),
            ("Packed Juice", 3000, "", ""),
        ]),
        ("Hot Beverages", "", [
            ("African Tea", 5000, "", ""),
            ("Spicy Tea", 5000, "", ""),
            ("Green Tea", 5000, "", "vegan"),
        ]),
    ],
}

DEFAULT_SETTINGS = {
    "venue_name": "Zaria Court Kigali",
    "whatsapp_url": config.WHATSAPP_URL,
    "venue_notice": "",
    "ordering_enabled": "1",
    "public_base_url": "",
}


def ensure_seeded() -> None:
    if db.setting("seeded") == "1":
        return

    now = config.now_iso()
    created: list[tuple[str, str, str]] = []

    with db.tx():
        for key, value in DEFAULT_SETTINGS.items():
            db.ex("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (key, value))

        for sort, (slug, name, kind, tagline, accent, logo, momo, phone, url, takes) in enumerate(VENDORS):
            cur = db.ex(
                "INSERT INTO vendors(slug,name,kind,tagline,accent,logo,momo_code,phone,"
                "external_url,accepts_orders,is_open,is_active,sort,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,1,1,?,?)",
                (slug, name, kind, tagline, accent, logo, momo, phone, url, takes, sort * 10, now),
            )
            vendor_id = cur.lastrowid

            for ci, (cat_name, note, items) in enumerate(MENUS.get(slug, [])):
                ccur = db.ex(
                    "INSERT INTO categories(vendor_id,name,note,sort,is_active)"
                    " VALUES(?,?,?,?,1)",
                    (vendor_id, cat_name, note, ci * 10),
                )
                cat_id = ccur.lastrowid
                for ii, (iname, price, desc, tags) in enumerate(items):
                    db.ex(
                        "INSERT INTO items(vendor_id,category_id,name,description,price_rwf,"
                        "tags,is_available,is_active,sort,created_at,updated_at)"
                        " VALUES(?,?,?,?,?,?,1,1,?,?,?)",
                        (vendor_id, cat_id, iname, desc, price, tags, ii * 10, now, now),
                    )

            if takes:
                username = slug.replace("-", "")[:20]
                temp = security.public_code()[:12]
                db.ex(
                    "INSERT INTO vendor_users(vendor_id,username,pw_hash,display,is_active,"
                    "must_change,created_at) VALUES(?,?,?,?,1,1,?)",
                    (vendor_id, username, security.hash_password(temp), name, now),
                )
                created.append(("vendor", username, temp))

        admin_temp = security.public_code()[:14]
        db.ex(
            "INSERT INTO admin_users(username,pw_hash,display,is_active,must_change,created_at)"
            " VALUES('admin',?,?,1,1,?)",
            (security.hash_password(admin_temp), "Zaria Admin", now),
        )
        created.append(("admin", "admin", admin_temp))

        # A starter block of tables so QR codes can be printed immediately.
        for zone, codes in (("Main floor", [f"A{i}" for i in range(1, 21)]),
                            ("Terrace", [f"T{i}" for i in range(1, 11)]),
                            ("VIP", [f"V{i}" for i in range(1, 7)])):
            for code in codes:
                db.ex(
                    "INSERT OR IGNORE INTO venue_tables(code,label,zone,is_active,created_at)"
                    " VALUES(?,?,?,1,?)",
                    (code, code, zone, now),
                )

        db.set_setting("seeded", "1")

    _print_credentials(created)


def _print_credentials(created: list[tuple[str, str, str]]) -> None:
    path = config.DATA_DIR / "FIRST-RUN-PASSWORDS.txt"
    lines = [
        "Zaria Court ordering system - first run",
        "=" * 52,
        "",
        "These one-time passwords were generated on first start.",
        "Every account must change its password at first sign-in.",
        "",
    ]
    for kind, username, temp in created:
        where = "/admin" if kind == "admin" else "/vendor"
        lines.append(f"  {where:<8}  {username:<16}  {temp}")
    lines += [
        "",
        "Delete this file once the passwords have been handed over.",
    ]
    text = "\n".join(lines)
    path.write_text(text, encoding="utf-8")

    print("\n" + text)
    print(f"\n  (also written to {path})\n")
