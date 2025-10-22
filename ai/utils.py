from google import genai
from google.genai import types
from django.conf import settings


client = genai.Client(api_key=settings.GEMINI_KEY)

def call_gemini_api(image_bytes: bytes, prompt: str) -> str:
    """Call Gemini API with image bytes and prompt addition, return extracted text."""
    
    # --- 3️⃣ Prepare the prompt ---
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
            prompt,
        ],
    )
    return response.text.strip()