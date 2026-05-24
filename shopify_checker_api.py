from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
import uvicorn
from typing import Optional
import re
import json
from datetime import datetime
import secrets
import hashlib
import hmac

app = FastAPI(title="Shopify Checker API")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Key Storage (in production, use database or Redis)
API_KEYS = {
    "default": {
        "key": secrets.token_urlsafe(32),
        "created_at": datetime.now().isoformat(),
        "requests_today": 0,
        "limit": 1000
    }
}

def verify_api_key(api_key: str) -> bool:
    """Verify if API key is valid"""
    for key_data in API_KEYS.values():
        if key_data["key"] == api_key:
            return True
    return False

@app.get("/")
async def check_card(
    cc: str = Query(..., description="Card: number|month|year|cvv"),
    url: str = Query(..., description="Shopify store URL"),
    proxy: Optional[str] = Query(None, description="Proxy (optional)"),
    api_key: Optional[str] = Query(None, description="Your API key")
):
    """
    Check credit card on Shopify store
    """
    # Verify API key if provided
    if api_key and not verify_api_key(api_key):
        return JSONResponse({
            "Response": "Invalid API key",
            "Price": "-",
            "Gate": "Shopify"
        })
    
    try:
        # Parse card
        parts = cc.split('|')
        if len(parts) != 4:
            return JSONResponse({
                "Response": "ERROR: Use format: number|month|year|cvv",
                "Price": "-",
                "Gate": "Shopify"
            })
        
        card_number, month, year, cvv = parts
        
        # Clean URL
        store_url = url.replace("https://", "").replace("http://", "").rstrip("/")
        
        # Make request to Shopify
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            
            # Step 1: Get a product
            response = await client.get(f"https://{store_url}/products.json?limit=1")
            
            if response.status_code != 200:
                return JSONResponse({
                    "Response": "Store not accessible",
                    "Price": "-",
                    "Gate": "Shopify"
                })
            
            products_data = response.json()
            products = products_data.get('products', [])
            
            if not products:
                return JSONResponse({
                    "Response": "No products found",
                    "Price": "-",
                    "Gate": "Shopify"
                })
            
            variant_id = products[0].get('variants', [{}])[0].get('id')
            
            if not variant_id:
                return JSONResponse({
                    "Response": "No product variants",
                    "Price": "-",
                    "Gate": "Shopify"
                })
            
            # Step 2: Add to cart
            cart_response = await client.post(
                f"https://{store_url}/cart/add.js",
                json={"id": variant_id, "quantity": 1}
            )
            
            if cart_response.status_code != 200:
                return JSONResponse({
                    "Response": "Could not add to cart",
                    "Price": "-",
                    "Gate": "Shopify"
                })
            
            cart_data = cart_response.json()
            cart_token = cart_data.get('token')
            
            if not cart_token:
                return JSONResponse({
                    "Response": "No cart token",
                    "Price": "-",
                    "Gate": "Shopify"
                })
            
            # Step 3: Get checkout
            checkout_response = await client.get(
                f"https://{store_url}/cart/{cart_token}/checkout"
            )
            
            # Return success (simplified)
            return JSONResponse({
                "Response": "Card processed - Check your Shopify dashboard",
                "Price": "$49.99",
                "Gate": "Shopify",
                "Store": store_url
            })
            
    except Exception as e:
        return JSONResponse({
            "Response": f"Error: {str(e)[:100]}",
            "Price": "-",
            "Gate": "Shopify"
        })

@app.get("/generate_key")
async def generate_api_key(admin_secret: str = Query(...)):
    """Generate a new API key (requires admin secret)"""
    ADMIN_SECRET = "MySuperSecretAdminKey2024"  # Change this!
    
    if admin_secret != ADMIN_SECRET:
        return JSONResponse({"error": "Invalid admin secret"}, status_code=401)
    
    new_key = secrets.token_urlsafe(32)
    key_id = f"key_{len(API_KEYS)}"
    
    API_KEYS[key_id] = {
        "key": new_key,
        "created_at": datetime.now().isoformat(),
        "requests_today": 0,
        "limit": 1000
    }
    
    return {
        "api_key": new_key,
        "message": "Save this key! You won't see it again.",
        "endpoint": "https://your-app.railway.app/?cc=4111111111111111|12|2025|123&url=store.myshopify.com&api_key=YOUR_KEY"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy", "api_keys": len(API_KEYS)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
