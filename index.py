import os
import csv
import json
import logging
import boto3
from openai import OpenAI

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
secrets_client = boto3.client("secretsmanager")

def get_openai_api_key():
    try:
        secret_name = os.environ.get("OPENAI_SECRET_NAME", "vehicle-generator/openai-api-key")
        response = secrets_client.get_secret_value(SecretId=secret_name)
        return response["SecretString"]
    except Exception as e:
        logger.error(f"Failed to retrieve OpenAI API key: {str(e)}")
        raise

client = OpenAI(api_key=get_openai_api_key())

def custom_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body)
    }

def handler(event, context):
    try:
        bucket = os.environ["BUCKET_NAME"]
        key = os.environ["CSV_KEY"]
        path = event["path"]
        query = event.get("queryStringParameters") or {}
        stock_number = query.get("stock")
        options = query.get("options")
        clean_carfax = query.get("cleanCarfax") == "true"
        carfax_one_owner = query.get("carfax1Owner") == "true"
        carfax_labels = []

        if clean_carfax:
            carfax_labels.append("Clean Carfax")

        if carfax_one_owner:
            carfax_labels.append("Carfax 1-Owner")

        prefix = ", ".join(carfax_labels)


        if not stock_number:
            return custom_response(400, {"error": "Missing stock number"})

        s3_object = s3.get_object(Bucket=bucket, Key=key)
        lines = s3_object["Body"].read().decode("utf-8").splitlines()
        reader = csv.DictReader(lines)

        stock_number = stock_number.upper()
        row = next((r for r in reader if r["stock_number"].upper() == stock_number), None)
        if not row:
            return custom_response(404, {"error": "Stock not found"})

        vehicle_data = {
            "year": row["year"],
            "make": row["make"],
            "model": row["model"],
            "trim": row.get("Trim", ""),
            "drivetrain": row["drivetrain"],
            "mileage": row["mileage.value"],
            "transmission": row["transmission"],
        }

        if path.endswith("/lookup"):
            return custom_response(200, vehicle_data)

        if path.endswith("/generate"):
            if not options:
                return custom_response(400, {"error": "Missing options"})

            show_drivetrain = row["drivetrain"].lower() in ["awd", "4wd"]

            prompt = f"""
You are writing compelling vehicle descriptions for our used car dealership vehicle ads for our website. Follow these rules:

Include the options I give in order order of most valuable to least, capitalizing the first letter of each word. Do not describe or add adjectives to any option.

After the options, add a dash (–), then start the vehicle description, don't make a new line.

When describing the vehicle, use anything you know of that particular model of vehicle, and really try to sell it, we want people to be very intrigued.

Only mention the drivetrain if it is AWD or 4WD.

Do not invent any condition, or carfax history.

Use a neutral, human tone — avoid robotic or overly rigid sentences.

Maximum 4 sentences.

Now write a description using the vehicle data below.

Vehicle: {row["year"]} {row["make"]} {row["model"]} {row.get("Trim", "")}
Mileage: {row["mileage.value"]} miles
{f"Drivetrain: {row['drivetrain']}" if show_drivetrain else ""}
Options: {options}
"""

            try:
                openai_response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=300
                )

                description = openai_response.choices[0].message.content.strip() + "\n\nAt Wallingford Auto Park, we've proudly served the community for over 30 years, offering quality used vehicles with transparent, no-haggle pricing. Our knowledgeable staff and no-pressure approach have helped thousands of customers drive away with confidence.\n\nPosted internet prices include Dealer Financing Savings of $750. Savings not available for cash or outside finance transactions. Must finance with dealer to qualify for all discounts and incentives included in online pricing. Pricing applies to in-stock vehicles only and must take delivery the same day."

                if prefix:
                    description = f"{prefix} - {description}"

                return custom_response(200, {
                    "vehicle": vehicle_data,
                    "description": description
                })

            except Exception as e:
                logger.exception("OpenAI generation error:")
                return custom_response(500, {"error": f"Failed to generate description: {str(e)}"})

        return custom_response(400, {"error": "Unknown path"})

    except Exception as e:
        logger.exception("Unhandled error:")
        return custom_response(500, {"error": f"Internal server error: {str(e)}"})
