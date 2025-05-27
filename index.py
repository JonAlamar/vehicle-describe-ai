
import boto3
import csv
import json
import os
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
bedrock = boto3.client("bedrock-runtime")

def response(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*"
        },
        "body": json.dumps(body)
    }

def handler(event, context):
    try:
        bucket = os.environ["BUCKET_NAME"]
        key = os.environ["CSV_KEY"]
        path = event["path"]  # Will be /lookup or /generate
        query = event.get("queryStringParameters") or {}
        stock_number = query.get("stock")
        options = query.get("options")

        if not stock_number:
            return response(400, {"error": "Missing stock number"})

        # Load the CSV from S3
        s3_object = s3.get_object(Bucket=bucket, Key=key)
        lines = s3_object["Body"].read().decode("utf-8").splitlines()
        reader = csv.DictReader(lines)

        # Match stock number
        row = next((r for r in reader if r["stock_number"] == stock_number), None)
        if not row:
            return response(404, {"error": "Stock not found"})

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
            return response(200, vehicle_data)

        if path.endswith("/generate"):
            if not options:
                return response(400, {"error": "Missing options"})

            intro = ""
            if "carfax 1 owner" in options.lower():
                intro += "Carfax 1 Owner. "
            elif "clean carfax" in options.lower():
                intro += "Clean Carfax. "

            show_drivetrain = row["drivetrain"].lower() in ["awd", "4wd"]

            prompt = f"""
You are a professional automotive copywriter. Write engaging, neutral, and confident descriptions for used vehicles.
Rules:
- Begin the first sentence with important options provided.
- If the user includes "clean Carfax" or "Carfax 1 Owner", put that first.
- Mention drivetrain only if it's AWD or 4WD.
- Do not mention vehicle condition.
- Avoid hype or assumptions—just factual, friendly copy.

Vehicle: {row["year"]} {row["make"]} {row["model"]} {row["Trim"]}
Mileage: {row["mileage.value"]} miles
Transmission: {row["transmission"]}
{f"Drivetrain: {row["drivetrain"]}" if show_drivetrain else ""}
Important features: {options}

Write a 3-4 sentence description.
"""

            completion = bedrock.invoke_model(
                modelId="anthropic.claude-3-5-haiku-20241022-v1:0",
                contentType="application/json",
                accept="application/json",
                body=json.dumps({
                    "prompt": f"\n\nHuman: {prompt}\n\nAssistant:",
                    "max_tokens_to_sample": 300,
                    "temperature": 0.7
                })
            )
            result = json.loads(completion["body"].read().decode())

            return response(200, {
                "vehicle": vehicle_data,
                "description": intro + result["completion"].strip()
            })

        return response(400, {"error": "Unknown path"})

    except Exception as e:
        logger.exception("Unhandled error:")
        return response(500, {"error": f"Internal server error: {str(e)}"})
