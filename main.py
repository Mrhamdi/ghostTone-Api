from fastapi import FastAPI, WebSocket
import json
from fastapi.middleware.cors import CORSMiddleware
import requests

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

waiting_users = []  # List to keep track of users waiting for a match

# Fetch country by IP (via ip-api service)
def get_country_by_ip(ip):
    url = f'http://ip-api.com/json/{ip}'
    try:
        response = requests.get(url)
        data = response.json()
        if data['status'] == 'fail':
            return None  # Return None if there's an error fetching the country
        return data['country']
    except Exception as e:
        #print(f"Error fetching country for IP {ip}: {e}")
        return None

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    global waiting_users
    data = await websocket.receive_text()
    peer_info = json.loads(data)  # Receiving peer_id and ip from the frontend

    # Matchmaking logic
    if waiting_users:
        matched_user = waiting_users.pop(0)  # Match with the first waiting user
        await matched_user["socket"].send_json({
            "status": "matched",
            "peer_id": peer_info["peer_id"],
            "country": get_country_by_ip(peer_info["ip"]),  # Send the matched user's country
        })
        await websocket.send_json({
            "status": "matched",
            "peer_id": matched_user["peer_id"],
            "country": matched_user["country"],
        })
    else:
        # Add this user to the waiting list
        waiting_users.append({
            "socket": websocket,
            "peer_id": peer_info["peer_id"],
            "country": get_country_by_ip(peer_info["ip"]),  # Send the matched user's country
        })
        await websocket.send_json({"status": "waiting"})

    try:
        while True:
            message = await websocket.receive_text()
            # Handle skip action
            if message == '{"action": "skip"}':
                for user in waiting_users:
                    if user["socket"] == websocket:
                        waiting_users.remove(user)
                        break
                for user in waiting_users:
                    if user["socket"] != websocket:
                        await user["socket"].send_json({
                            "status": "skipped",
                            "message": "Your partner has skipped the call."
                        })
            elif message == '{"action": "cancel"}':
                # Handle call hang-up action
                for user in waiting_users:
                    if user["socket"] == websocket:
                        waiting_users.remove(user)
                        break
                await websocket.send_json({"status": "call_ended"})
    except Exception as e:
        print(f"Error: {e}")
        # Clean up when the connection closes
        waiting_users = [user for user in waiting_users if user["socket"] != websocket]
