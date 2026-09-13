import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
 
response = client.responses.create(
  model="gpt-5.6-luna",
  input="write 10 words about yourself",
  store=True,
)

print(response.output_text);
