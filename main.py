from fastapi import FastAPI, WebSocket
import json
from fastapi.middleware.cors import CORSMiddleware




app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],  
    allow_headers=["*"], 
)

waiting_users = [] 

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    global waiting_users
    data = await websocket.receive_text()
    peer_info = json.loads(data) 
    if waiting_users:
        matched_user = waiting_users.pop(0)
        await matched_user["socket"].send_json({
            "status": "matched",
            "peer_id": peer_info["peer_id"],
            "country": peer_info["country"]
        })
        await websocket.send_json({
            "status": "matched",
            "peer_id": matched_user["peer_id"],
            "country": matched_user["country"]
        })
    else:
        waiting_users.append({"socket": websocket, "peer_id": peer_info["peer_id"], "country": peer_info["country"]})
        await websocket.send_json({"status": "waiting"})

    try:
        while True:
            message = await websocket.receive_text()
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
    except Exception as e:
        print(f"Error: {e}")
        waiting_users = [user for user in waiting_users if user["socket"] != websocket]
