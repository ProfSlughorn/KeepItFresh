import requests
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from user_preferences.utils import get_global_household_staples


def get_access_token(client_id, client_secret):
    """
    Fetches an access token from FatSecret API.
    """
    print("Fetching access token...")
    url = "https://oauth.fatsecret.com/connect/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "client_credentials",
        "scope": "premier",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    response = requests.post(url, headers=headers, data=data)

    if response.status_code == 200:
        access_token = response.json().get("access_token")
        return access_token
    else:
        raise Exception(f"Failed to get access token: {response.text}")


def get_recipes(access_token, search_expression, max_results=10, page_number=0):
    """
    Fetches recipes matching the search expression from FatSecret API.
    """
    url = "https://platform.fatsecret.com/rest/recipes/search/v3"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "search_expression": search_expression,
        "max_results": max_results,
        "page_number": page_number,
        "format": "json"
    }
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"API Error: {response.status_code} - {response.text}")


def get_recipe_details(access_token, recipe_id):
    """
    Fetches detailed information about a recipe by its ID from FatSecret API.
    """
    url = "https://platform.fatsecret.com/rest/recipe/v2"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "recipe_id": recipe_id,
        "format": "json"
    }
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"API Error: {response.status_code} - {response.text}")

def get_food_details(access_token, food_id):
    """
    Fetches detailed information about food by its ID from FatSecret API.
    Includes allergen and dietary preference information.
    """
    url = f"https://platform.fatsecret.com/rest/food/v4?food_id={food_id}&format=json&include_food_attributes=true"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"API Error: {response.status_code} - {response.text}")


def match_recipes(access_token, user_ingredients, household_staples, dietary_preferences=[], max_results=10):
    """
    Matches recipes based on user ingredients, household staples, and dietary preferences.
    Returns only missing ingredients.
    """
    all_matched_recipes = []
    for ingredient in user_ingredients:  # Search for each user ingredient
        recipes = get_recipes(access_token, ingredient, max_results=max_results)
        if "recipes" in recipes and "recipe" in recipes["recipes"]:
            for recipe in recipes["recipes"]["recipe"]:
                recipe_id = recipe["recipe_id"]

                # Fetch detailed recipe information
                recipe_details = get_recipe_details(access_token, recipe_id)
                if "recipe" not in recipe_details:
                    continue  # Skip this recipe if details are missing

                # Extract ingredients from recipe
                ingredients_data = recipe_details["recipe"].get("ingredients", {}).get("ingredient", [])
                recipe_ingredients = [
                    {"food_name": ingredient["food_name"].lower(), "food_id": ingredient.get("food_id")}
                    for ingredient in ingredients_data
                ] if isinstance(ingredients_data, list) else []

                # Dietary requirements check
                recipe_compatible = True
                for ingredient in recipe_ingredients:
                    food_id = ingredient.get("food_id")
                    if food_id:  # Ensure food_id is present to check
                        food_details = get_food_details(access_token, food_id)
                        allergens = food_details.get("food", {}).get("food_attributes", {}).get("allergens", {}).get("allergen", [])
                        preferences = food_details.get("food", {}).get("food_attributes", {}).get("preferences", {}).get("preference", [])

                        # Check allergens and dietary preferences
                        if dietary_preferences:
                            for restriction in dietary_preferences:
                                if restriction == "gluten-free":
                                    gluten = next((a for a in allergens if a.get("name").lower() == "gluten"), None)
                                    if gluten and gluten.get("value") == "1":  # Contains gluten
                                        recipe_compatible = False
                                elif restriction == "egg-free":
                                    egg = next((a for a in allergens if a.get("name").lower() == "egg"), None)
                                    if egg and egg.get("value") == "1":  # Contains egg
                                        recipe_compatible = False
                                elif restriction == "dairy-free":
                                    dairy = next((a for a in allergens if a.get("name").lower() in ["milk", "lactose"]), None)
                                    if dairy and dairy.get("value") == "1":  # Contains dairy
                                        recipe_compatible = False
                                elif restriction == "vegan":
                                    vegan = next((p for p in preferences if p.get("name").lower() == "vegan"), None)
                                    if vegan and vegan.get("value") == "0":  # Not vegan
                                        recipe_compatible = False
                                elif restriction == "vegetarian":
                                    vegetarian = next((p for p in preferences if p.get("name").lower() == "vegetarian"), None)
                                    if vegetarian and vegetarian.get("value") == "0":  # Not vegetarian
                                        recipe_compatible = False
                                elif restriction == "soy-free":
                                    soy = next((a for a in allergens if a.get("name").lower() == "soy"), None)
                                    if soy and soy.get("value") == "1":  # Contains soy
                                        recipe_compatible = False

                    if not recipe_compatible:
                        break

                if not recipe_compatible:
                    continue  # Skip this recipe if it doesn't meet dietary preferences

                # Matching logic
                matched = [
                    ingredient["food_name"]
                    for ingredient in recipe_ingredients
                    if any(user_ing in ingredient["food_name"] for user_ing in (user_ingredients + household_staples))
                ]

                # Missing ingredients: those not in matched
                missing_ingredients = [
                    ingredient["food_name"]
                    for ingredient in recipe_ingredients
                    if ingredient["food_name"] not in matched
                ]

                total_ingredients = len(recipe_ingredients)
                match_percentage = (len(matched) / total_ingredients) * 100 if total_ingredients > 0 else 0

                if match_percentage < 50:  # Skip recipes with less than 50% match
                    continue

                # Get preparation and cooking times
                preparation_time = recipe_details["recipe"].get("preparation_time_min", "N/A")
                cooking_time = recipe_details["recipe"].get("cooking_time_min", "N/A")

                # Get recipe image URL
                recipe_images = recipe_details["recipe"].get("recipe_images", {}).get("recipe_image", [])
                recipe_image = (
                    recipe_images if isinstance(recipe_images, str) else recipe_images[0] if recipe_images else "N/A"
                )

                # Append recipe with missing ingredients (no matched ingredients)
                all_matched_recipes.append(
                    {
                        "recipe_id": recipe_id,
                        "recipe_name": recipe_details["recipe"]["recipe_name"],
                        "missing_ingredients": missing_ingredients,
                        "match_percentage": match_percentage,
                        "preparation_time": preparation_time,
                        "cooking_time": cooking_time,
                        "recipe_image": recipe_image,
                    }
                )

    # Sort recipes by match_percentage, descending
    return sorted(all_matched_recipes, key=lambda x: x["match_percentage"], reverse=True)


@csrf_exempt
@csrf_exempt
def recommend_recipes(request):
    """
    API endpoint to recommend recipes based on leftover ingredients.
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            user_ingredients = data.get('ingredients', [])
            dietary_preferences = data.get('dietary_preferences', [])

            if not isinstance(user_ingredients, list):
                return JsonResponse({'error': 'Ingredients must be a list'}, status=400)

            if not isinstance(dietary_preferences, list):
                return JsonResponse({'error': 'Dietary preferences must be a list'}, status=400)

            if not user_ingredients:
                return JsonResponse({'error': 'No ingredients provided'}, status=400)

            household_staples = get_global_household_staples()

            CLIENT_ID = "4e3672bde10043e4b3f0b89b33f408a6"
            CLIENT_SECRET = "44b56dd7199e4d2286807ca4aa787774"
            access_token = get_access_token(CLIENT_ID, CLIENT_SECRET)

            recipes = match_recipes(access_token, user_ingredients, household_staples, dietary_preferences, max_results=10)
            return JsonResponse({'recipes': recipes}, status=200)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Invalid request method'}, status=405)


@csrf_exempt
def recipe_detail(request, recipe_id):
    """
    API endpoint to fetch detailed information for a specific recipe.
    """
    if request.method == 'GET':
        try:
            CLIENT_ID = "4e3672bde10043e4b3f0b89b33f408a6"
            CLIENT_SECRET = "44b56dd7199e4d2286807ca4aa787774"
            access_token = get_access_token(CLIENT_ID, CLIENT_SECRET)

            recipe_details = get_recipe_details(access_token, recipe_id)
            return JsonResponse(recipe_details, status=200)

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Invalid request method'}, status=405)
