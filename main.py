from fastapi import FastAPI, WebSocket, HTTPException
import json
from fastapi.middleware.cors import CORSMiddleware
import requests
from datetime import datetime, timedelta
import asyncio
from typing import Dict, List, Optional
import uuid
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

waiting_users = []  
active_connections = {}  # Track active connections
online_users = {}  # Track all online users with their info
webrtc_rooms = {}  # Track WebRTC rooms/sessions
user_stats = {
    "total_online": 0,
    "waiting": 0,
    "in_call": 0,
    "countries": {}
}

# WebRTC signaling message types
class SignalingMessage:
    OFFER = "offer"
    ANSWER = "answer"
    ICE_CANDIDATE = "ice-candidate"
    JOIN_ROOM = "join-room"
    LEAVE_ROOM = "leave-room"
    ROOM_JOINED = "room-joined"
    ROOM_LEFT = "room-left"
    USER_JOINED = "user-joined"
    USER_LEFT = "user-left"

# Country flag mapping
COUNTRY_FLAGS = {
    "United States": "🇺🇸", "Canada": "🇨🇦", "United Kingdom": "🇬🇧", "Germany": "🇩🇪",
    "France": "🇫🇷", "Italy": "🇮🇹", "Spain": "🇪🇸", "Netherlands": "🇳🇱",
    "Sweden": "🇸🇪", "Norway": "🇳🇴", "Denmark": "🇩🇰", "Finland": "🇫🇮",
    "Poland": "🇵🇱", "Russia": "🇷🇺", "Ukraine": "🇺🇦", "Turkey": "🇹🇷",
    "Japan": "🇯🇵", "South Korea": "🇰🇷", "China": "🇨🇳", "India": "🇮🇳",
    "Australia": "🇦🇺", "New Zealand": "🇳🇿", "Brazil": "🇧🇷", "Argentina": "🇦🇷",
    "Mexico": "🇲🇽", "Chile": "🇨🇱", "Colombia": "🇨🇴", "Peru": "🇵🇪",
    "South Africa": "🇿🇦", "Egypt": "🇪🇬", "Nigeria": "🇳🇬", "Kenya": "🇰🇪",
    "Saudi Arabia": "🇸🇦", "UAE": "🇦🇪", "Israel": "🇮🇱", "Thailand": "🇹🇭",
    "Vietnam": "🇻🇳", "Indonesia": "🇮🇩", "Malaysia": "🇲🇾", "Singapore": "🇸🇬",
    "Philippines": "🇵🇭", "Taiwan": "🇹🇼", "Hong Kong": "🇭🇰", "Unknown": "🌍"
}

def get_country_by_ip(ip):
    url = f'http://ip-api.com/json/{ip}'
    try:
        response = requests.get(url)
        data = response.json()
        if data['status'] == 'fail':
            return None, "🌍"
        country = data['country']
        flag = COUNTRY_FLAGS.get(country, "🌍")
        return country, flag
    except Exception as e:
        print(f"Error fetching country for IP {ip}: {e}")
        return None, "🌍"

def update_user_stats():
    """Update user statistics"""
    global user_stats
    user_stats["total_online"] = len(online_users)
    user_stats["waiting"] = len(waiting_users)
    user_stats["in_call"] = len(active_connections) // 2  # Each call has 2 users
    
    # Count users by country
    country_counts = {}
    for user_info in online_users.values():
        country = user_info.get('country', 'Unknown')
        country_counts[country] = country_counts.get(country, 0) + 1
    user_stats["countries"] = country_counts

def create_webrtc_room():
    """Create a new WebRTC room"""
    room_id = str(uuid.uuid4())
    webrtc_rooms[room_id] = {
        "users": [],
        "created_at": datetime.now()
    }
    return room_id

def join_webrtc_room(room_id, user_socket, user_info):
    """Join a WebRTC room"""
    if room_id not in webrtc_rooms:
        return False
    
    webrtc_rooms[room_id]["users"].append({
        "socket": user_socket,
        "user_info": user_info
    })
    return True

def leave_webrtc_room(room_id, user_socket):
    """Leave a WebRTC room"""
    if room_id not in webrtc_rooms:
        return
    
    webrtc_rooms[room_id]["users"] = [
        user for user in webrtc_rooms[room_id]["users"] 
        if user["socket"] != user_socket
    ]
    
    # Clean up empty rooms
    if not webrtc_rooms[room_id]["users"]:
        del webrtc_rooms[room_id]

async def send_to_room_users(room_id, message, exclude_socket=None):
    """Send message to all users in a room except the sender"""
    if room_id not in webrtc_rooms:
        return
    
    for user in webrtc_rooms[room_id]["users"]:
        if user["socket"] != exclude_socket:
            try:
                await user["socket"].send_json(message)
            except Exception as e:
                logger.error(f"Error sending message to room user: {e}")

async def handle_webrtc_signaling(websocket, message_data):
    """Handle WebRTC signaling messages"""
    message_type = message_data.get("type")
    room_id = message_data.get("roomId")
    
    if message_type == SignalingMessage.JOIN_ROOM:
        # User wants to join a room
        if not room_id:
            # Create new room
            room_id = create_webrtc_room()
        
        # Get user info
        user_info = online_users.get(websocket, {})
        
        if join_webrtc_room(room_id, websocket, user_info):
            await websocket.send_json({
                "type": SignalingMessage.ROOM_JOINED,
                "roomId": room_id
            })
            
            # Notify other users in the room
            await send_to_room_users(room_id, {
                "type": SignalingMessage.USER_JOINED,
                "userInfo": user_info
            }, exclude_socket=websocket)
    
    elif message_type == SignalingMessage.LEAVE_ROOM:
        if room_id:
            leave_webrtc_room(room_id, websocket)
            await websocket.send_json({
                "type": SignalingMessage.ROOM_LEFT,
                "roomId": room_id
            })
            
            # Notify other users in the room
            await send_to_room_users(room_id, {
                "type": SignalingMessage.USER_LEFT,
                "userInfo": online_users.get(websocket, {})
            }, exclude_socket=websocket)
    
    elif message_type in [SignalingMessage.OFFER, SignalingMessage.ANSWER, SignalingMessage.ICE_CANDIDATE]:
        # Forward WebRTC signaling messages to other users in the room
        if room_id:
            await send_to_room_users(room_id, message_data, exclude_socket=websocket)

def cleanup_user(user_socket):
    """Remove user from waiting list and active connections"""
    global waiting_users, active_connections, online_users
    
    # Remove from waiting list
    waiting_users = [user for user in waiting_users if user["socket"] != user_socket]
    
    # Remove from online users
    if user_socket in online_users:
        del online_users[user_socket]
    
    # Remove from active connections
    if user_socket in active_connections:
        partner_socket = active_connections[user_socket]
        if partner_socket in active_connections:
            del active_connections[partner_socket]
        del active_connections[user_socket]
        
        # Notify partner about disconnection
        try:
            if partner_socket and partner_socket.client_state.name == "CONNECTED":
                asyncio.create_task(partner_socket.send_json({
                    "status": "partner_disconnected",
                    "message": "Your partner has disconnected."
                }))
        except Exception as e:
            print(f"Error notifying partner: {e}")
    
    # Update stats
    update_user_stats()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    global waiting_users, active_connections, online_users
    
    try:
        while True:
            message = await websocket.receive_text()
            message_data = json.loads(message)
            
            # Handle initial connection (matchmaking)
            if "peer_id" in message_data and "ip" in message_data:
                # Get country and flag for the new user
                country, flag = get_country_by_ip(message_data["ip"])
                user_country = country if country else "Unknown"
                user_flag = flag
                
                # Add user to online users
                online_users[websocket] = {
                    "peer_id": message_data["peer_id"],
                    "ip": message_data["ip"],
                    "country": user_country,
                    "flag": user_flag,
                    "joined_at": datetime.now()
                }
                
                if waiting_users:
                    matched_user = waiting_users.pop(0)  
                    matched_user_country, matched_user_flag = get_country_by_ip(matched_user["ip"])
                    matched_country = matched_user_country if matched_user_country else "Unknown"
                    matched_flag = matched_user_flag

                    # Create a WebRTC room for the matched users
                    room_id = create_webrtc_room()
                    
                    # Add both users to the room
                    join_webrtc_room(room_id, websocket, online_users[websocket])
                    join_webrtc_room(room_id, matched_user["socket"], {
                        "peer_id": matched_user["peer_id"],
                        "ip": matched_user["ip"],
                        "country": matched_country,
                        "flag": matched_flag,
                        "joined_at": datetime.now()
                    })

                    # Track active connection
                    active_connections[websocket] = matched_user["socket"]
                    active_connections[matched_user["socket"]] = websocket

                    await matched_user["socket"].send_json({
                        "status": "matched",
                        "peer_id": message_data["peer_id"],
                        "country": f"{user_flag} {user_country}",
                        "roomId": room_id
                    })
                    await websocket.send_json({
                        "status": "matched",
                        "peer_id": matched_user["peer_id"],
                        "country": f"{matched_flag} {matched_country}",
                        "roomId": room_id
                    })
                else:
                    waiting_users.append({
                        "socket": websocket,
                        "peer_id": message_data["peer_id"],
                        "ip": message_data["ip"],
                        "country": user_country,
                        "flag": user_flag
                    })
                    await websocket.send_json({"status": "waiting"})
                
                # Update stats
                update_user_stats()
            
            # Handle WebRTC signaling messages
            elif "type" in message_data:
                await handle_webrtc_signaling(websocket, message_data)
            
            # Handle legacy actions
            elif message == '{"action": "skip"}':
                cleanup_user(websocket)
                # Notify any remaining waiting users
                for user in waiting_users:
                    if user["socket"] != websocket:
                        await user["socket"].send_json({
                            "status": "skipped",
                            "message": "Your partner has skipped the call."
                        })
            elif message == '{"action": "cancel"}':
                # Handle call hang-up action
                cleanup_user(websocket)
                await websocket.send_json({"status": "call_ended"})
                
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        # Clean up when the connection closes
        cleanup_user(websocket)

# API endpoints for statistics
@app.get("/stats")
async def get_stats():
    """Get current user statistics"""
    update_user_stats()
    return user_stats

@app.get("/countries")
async def get_countries():
    """Get list of countries with flags"""
    return {
        "countries": [
            {"name": country, "flag": flag, "count": user_stats["countries"].get(country, 0)}
            for country, flag in COUNTRY_FLAGS.items()
        ]
    }
