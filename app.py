import streamlit as st
import pandas as pd
from datetime import date, timedelta
import ollama
import json
from PIL import Image
import pytesseract
import requests

#config
st.set_page_config(page_title="rescueBytes")
st.title("rescueBytes")

#secrets
SPOONACULAR_API_KEY = st.secrets.get("SPOONACULAR_API_KEY", "")
OLLAMA_API_KEY = st.secrets.get("OLLAMA_API_KEY", "")

#ollama init
client = ollama.Client(
    host="https://ollama.com",
    headers={
        "Authorization": f"Bearer {OLLAMA_API_KEY}"
    }
)

#init tabs
upload, pantry, recipes = st.tabs(["Upload", "Pantry", "Recipes"])

#init pantry
if "pantry" not in st.session_state:
    try:
        with open("saved.json", "r") as save:
            data = json.load(save)

        st.session_state.pantry = (pd.DataFrame(data) if data else pd.DataFrame({"Item": [], "Expiry": [], "Days Left": []}))

    except (FileNotFoundError, json.JSONDecodeError):
        st.session_state.pantry = pd.DataFrame({"Item": [], "Expiry": [], "Days Left": []})

def getExpiry(items):
    prompt = f"""
        You are a food storage expert.


        You will be given a list of different items seperated by new lines.
        Filter out all non-food items, and then for every food item, remove the price and convert the item to a title case.
        Then estimate how many days each food item remains usable
        after purchase when stored correctly.

        Rules:
        - Assume item was purchased today.
        - Assume refrigeration when required.
        - Return ONLY valid JSON.
        - Keys must match the item names exactly.
        - Values must be integers representing days.

        Example:

        {{
        "Milk": 7,
        "Eggs": 21,
        "Bread": 6
        }}

        Items:
        {json.dumps(items)}
    """

    response = client.chat(
        model="gpt-oss:120b-cloud",
        messages=[{
            "role": "user",
            "content": prompt
        }]
    )
    content = response["message"]["content"].strip()
    estimate = json.loads(content)
    return {str(k): int(v) for k, v in estimate.items()}

def add_to_pantry(items):
        expiries = getExpiry(items)
        new_rows = []
        if not expiries:
            return -1
        for item, exp in expiries.items():
            days=(exp if exp else 7)
            expiry = date.today()+timedelta(days=int(days))
            new_rows.append({"Item": item, "Expiry": expiry, "Days Left": days})
        if new_rows:
            st.session_state.pantry = pd.concat([st.session_state.pantry, pd.DataFrame(new_rows)], ignore_index=True)
            st.session_state.pantry = st.session_state.pantry.drop_duplicates()
        with open("saved.json", "w") as save:
            json.dump(st.session_state.pantry.to_dict(orient="records"), save, indent=4, default=str)
        return 0

def extract_image(img):
    image = Image.open(img)
    st.image(image, "Your Photo")
    text = pytesseract.image_to_string(image)
    with st.expander("Extracted text"):
        st.text(text)
    submit = st.button("Add items")
    items = text.splitlines()
    if submit:
        with st.spinner("Adding items...", show_time=True):
            status = add_to_pantry(items)
            if status == -1:
                st.warning("No valid food items recognised.")
            else:
                st.success("Items added successfully.")

def get_recipe_suggestions(ingredients,number=10):
    if not ingredients:
        return []

    try:
        response = requests.get(
            "https://api.spoonacular.com/recipes/findByIngredients",
            params={
                "ingredients": ','.join(ingredients),
                "number": number,
                "ranking": 2,
                "ignorePantry": False,
                "apiKey": SPOONACULAR_API_KEY,
            },
            timeout=20,
        )

        response.raise_for_status()
        return response.json()

    except Exception as e:
        st.error(
            f"Recipe search failed: {e}"
        )
        return []
with upload:
    st.header("Upload items")
    #RECEIPT

    receipt = st.file_uploader("Upload receipt", type=['jpg', 'jpeg', 'png', 'heic'])
        
    if receipt:
        extract_image(receipt)

    st.divider()

    #MANUAL
    with st.form("manual_upload_form"):
        manualInput = st.text_area("or enter items manually, one per line", placeholder="e.g\nMilk\nPasta\nCrisps")
        submit = st.form_submit_button("Add items")
        if submit:
            items = manualInput.splitlines()
            with st.spinner("Adding items...", show_time=True):
                add_to_pantry(items)
                st.success("Items added successfully.")
    st.divider()
    with st.expander("or take a photo of your receipt"):
        camera = st.camera_input("Take a photo of a receipt")
        if camera:
            extract_image(camera)
with pantry:
    if len(st.session_state.pantry["Item"]) > 0:
        st.text("Double click on boxes to edit.")
    st.session_state.pantry = st.data_editor(st.session_state.pantry)
    expiring = st.session_state.pantry[st.session_state.pantry["Days Left"] < 3]
    clear = st.button("Clear pantry")
    if clear:
        st.session_state.pantry = pd.DataFrame({"Item": [], "Expiry": [], "Days Left": []})
        with open("saved.json", 'w') as save:
            save.write('')
    if len(expiring):
        sep = '\n'.join(expiring['Item'].astype(str))
        st.warning(f"The following items will expire in under 3 days:\n{sep}")
    elif len(st.session_state.pantry["Item"]) > 0:
        st.info("No items expiring in next 3 days.")
    else:
        st.info("Pantry is empty - go to upload to add more items.")
with recipes:

    if len(st.session_state.pantry):
        pantry_df = (st.session_state.pantry.copy())
        urgent_items = (pantry_df[pantry_df["Days Left"]<=3]["Item"].tolist())

        if urgent_items:
            st.warning("Prioritising recipes for: " + ", ".join(urgent_items))
            ingredients = (urgent_items)

        else:
            ingredients = (pantry_df["Item"].tolist())
            st.info("No urgent items found, using pantry ingredients.")

        st.write("**Ingredients being used:**")

        st.write(", ".join(ingredients))
        number = st.text_input("", placeholder="Number of recipes (Default = 10)")
        time = st.slider("Recipe cooking time", min_value=5, max_value=180)

        vegetarian = st.checkbox("Vegetarian")
        vegan = st.checkbox("Vegan")
        halal = st.checkbox("Halal")

        if st.button("Find Recipes"):
            
            with st.spinner("Searching recipes...", show_time=True):
                try:
                    number = int(number)
                    if number >= 100: raise ValueError
                except Exception:
                    st.warning(f"\'{number}\' is not a valid number of recipes. Setting to 10.")
                    number=10

                recipes = (get_recipe_suggestions(ingredients, number=number))

            if recipes:

                st.success(f"Found {len(recipes)} recipes")

                for recipe in recipes:

                    title = recipe["title"]
                    recipe_id = recipe["id"]
                    time = recipe.get("readyInMinutes", "120")

                    image = recipe.get("image")

                    used_count = (recipe.get("usedIngredientCount", 0))
                    missed_count = (recipe.get("missedIngredientCount", 0))

                    recipe_url = (
                        f"https://spoonacular.com/recipes/"
                        f"{title.lower().replace(' ','-')}"
                        f"-{recipe_id}"
                    )

                    with st.container():
                        col1, col2 = (
                            st.columns(
                                [1, 3]
                            )
                        )

                        with col1:
                            if image:
                                st.image(image, width=180)

                        with col2:
                            st.subheader(title)

                            st.write(f"Uses {used_count} pantry ingredients")
                            st.write(f"Missing {missed_count} ingredients")
                            st.write(f"Time taken to cook: {time} minutes")
                            st.link_button("View Recipe",recipe_url,)

                        st.divider()

            else:
                st.info("No recipes found.")

    else:

        st.info(
            "Add some food items to your pantry first."
        )

