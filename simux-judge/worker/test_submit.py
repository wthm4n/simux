import pika
import json
import uuid
import time

def submit(name, language, code, test_cases):
    submission = {
        "id": str(uuid.uuid4()),
        "language": language,
        "code": code,
        "test_cases": test_cases
    }

    connection = pika.BlockingConnection(
        pika.ConnectionParameters(
            host="host.docker.internal",
            credentials=pika.PlainCredentials("admin", "admin123")
        )
    )
    channel = connection.channel()
    channel.queue_declare(queue="submissions", durable=True)
    channel.basic_publish(
        exchange="",
        routing_key="submissions",
        body=json.dumps(submission),
        properties=pika.BasicProperties(delivery_mode=2)
    )
    connection.close()
    print(f"[{name}] Submitted! ID: {submission['id']}")

test_cases = [
    {"input": "5",   "expected_output": "10"},
    {"input": "0",   "expected_output": "0"},
    {"input": "100", "expected_output": "200"},
]

# ✅ Should be AC
submit("AC Test", "python", """
n = int(input())
print(n * 2)
""", test_cases)

time.sleep(2)

# ❌ Should be WA
submit("WA Test", "python", """
n = int(input())
print(n * 3)
""", test_cases)

time.sleep(2)

# 💀 Should be RE
submit("RE Test", "python", """
print(1/0)
""", test_cases)

time.sleep(2)

# ⏱ Should be TLE
submit("TLE Test", "python", """
while True:
    pass
""", test_cases)

print("\nAll submitted! Watch the worker terminal.")