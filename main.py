from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from datetime import datetime
from typing import Dict, List
import uuid
from pymongo import MongoClient
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Create templates directory if it doesn't exist
os.makedirs("templates", exist_ok=True)
templates = Jinja2Templates(directory="templates")

# Initialize in-memory storage as fallback
users = ["Vamshi", "Akilesh", "Shashank", "Abhishek","Aneesh"]
messages_storage = []
notifications_storage = {user: [] for user in users}

# MongoDB connection with better error handling for serverless
try:
    MONGODB_URI = "mongodb+srv://duvamshi10_db_user:vamshidu@cluster0.jt9a26l.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
    client = MongoClient(
        MONGODB_URI,
        serverSelectionTimeoutMS=5000,  # 5 second timeout
        connectTimeoutMS=10000,
        socketTimeoutMS=10000,
        retryWrites=True,
        maxPoolSize=10
    )

    # Test the connection
    client.admin.command('ping')
    logger.info("✅ Successfully connected to MongoDB!")

    db = client['chat_system']
    messages_collection = db['messages']
    notifications_collection = db['notifications']
    users_collection = db['users']

    # Initialize users in database
    try:
        for user in users:
            users_collection.update_one(
                {"username": user},
                {"$setOnInsert": {"username": user, "created_at": datetime.now()}},
                upsert=True
            )
        logger.info("✅ Users initialized in MongoDB")
    except Exception as e:
        logger.error(f"❌ Failed to initialize users in MongoDB: {e}")

except Exception as e:
    logger.error(f"❌ MongoDB connection failed: {e}")
    logger.info("🔄 Using in-memory storage instead...")
    client = None
    db = None
    messages_collection = None
    notifications_collection = None
    users_collection = None


# Homepage with form
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    try:
        return templates.TemplateResponse("home.html", {
            "request": request,
            "error": None,
            "users": users
        })
    except Exception as e:
        logger.error(f"Template error: {e}")
        return HTMLResponse(content=f"<h1>Error loading template: {e}</h1>", status_code=500)


# Form submission
@app.post("/", response_class=HTMLResponse)
async def check_user(request: Request, username: str = Form(...)):
    if username not in users:
        return templates.TemplateResponse("home.html", {
            "request": request,
            "error": "User not found!",
            "users": users
        })
    return RedirectResponse(f"/{username}", status_code=303)


# User page
@app.get("/{username}", response_class=HTMLResponse)
async def get_user(request: Request, username: str):
    if username not in users:
        raise HTTPException(status_code=404, detail="User not found")

    # Get selected user from query parameter
    selected_user = request.query_params.get("selected")

    # Get other users (excluding current user)
    other_users = [user for user in users if user != username]

    # Get user's unread notifications
    user_notifications = []
    if notifications_collection is not None:
        try:
            user_notifications = list(notifications_collection.find({
                "to_user": username,
                "read": False
            }).sort("timestamp", -1))

            # Convert ObjectId to string for template
            for notif in user_notifications:
                notif['_id'] = str(notif['_id'])
        except Exception as e:
            logger.error(f"Error fetching notifications from MongoDB: {e}")
            user_notifications = notifications_storage.get(username, [])
    else:
        user_notifications = notifications_storage.get(username, [])

    # Filter messages for the current conversation
    conversation_messages = []
    if selected_user and selected_user in other_users:
        if messages_collection is not None:
            try:
                # Get messages between current user and selected user
                conversation_messages = list(messages_collection.find({
                    "$or": [
                        {"from_user": username, "to_user": selected_user},
                        {"from_user": selected_user, "to_user": username}
                    ]
                }).sort("timestamp", 1))

                # Convert ObjectId to string for template
                for msg in conversation_messages:
                    msg['_id'] = str(msg['_id'])
            except Exception as e:
                logger.error(f"Error fetching messages from MongoDB: {e}")
                conversation_messages = [
                    msg for msg in messages_storage
                    if (msg['from_user'] == username and msg['to_user'] == selected_user) or
                       (msg['from_user'] == selected_user and msg['to_user'] == username)
                ]
        else:
            conversation_messages = [
                msg for msg in messages_storage
                if (msg['from_user'] == username and msg['to_user'] == selected_user) or
                   (msg['from_user'] == selected_user and msg['to_user'] == username)
            ]

        # Mark notifications from selected user as read when viewing the conversation
        if notifications_collection is not None:
            try:
                notifications_collection.update_many(
                    {
                        "from_user": selected_user,
                        "to_user": username,
                        "read": False
                    },
                    {"$set": {"read": True}}
                )
            except Exception as e:
                logger.error(f"Error updating notifications in MongoDB: {e}")
        else:
            # Update in-memory storage
            notifications_storage[username] = [
                notif for notif in notifications_storage.get(username, [])
                if notif.get('from_user') != selected_user
            ]

    return templates.TemplateResponse("index.html", {
        "request": request,
        "username": username,
        "users": other_users,
        "selected_user": selected_user,
        "messages": conversation_messages,
        "notifications": user_notifications
    })


# Handle message submission
@app.post("/{current_username}/send_message")
async def send_message(current_username: str, request: Request,
                       message: str = Form(...),
                       to_user: str = Form(...)):
    if current_username not in users or to_user not in users:
        raise HTTPException(status_code=400, detail="Invalid user")

    # Prepare message data
    new_message = {
        "id": str(uuid.uuid4()),
        "from_user": current_username,
        "to_user": to_user,
        "message": message,
        "timestamp": datetime.now(),
        "date": datetime.now().strftime("%Y-%m-%d")
    }

    # Prepare notification data
    notification = {
        "id": str(uuid.uuid4()),
        "from_user": current_username,
        "to_user": to_user,
        "message": message,
        "timestamp": datetime.now(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "type": "new_message",
        "read": False
    }

    # Store in MongoDB if available, otherwise use in-memory storage
    if messages_collection is not None:
        try:
            messages_collection.insert_one(new_message)
            notifications_collection.insert_one(notification)
            logger.info(f"✅ Message stored in MongoDB: {current_username} -> {to_user}: {message}")
        except Exception as e:
            logger.error(f"❌ Failed to store in MongoDB, using in-memory: {e}")
            messages_storage.append(new_message)
            if to_user in notifications_storage:
                notifications_storage[to_user].append(notification)
            else:
                notifications_storage[to_user] = [notification]
    else:
        messages_storage.append(new_message)
        if to_user in notifications_storage:
            notifications_storage[to_user].append(notification)
        else:
            notifications_storage[to_user] = [notification]
        logger.info(f"✅ Message stored in memory: {current_username} -> {to_user}: {message}")

    # Redirect back to the same user's page with the selected user
    return RedirectResponse(f"/{current_username}?selected={to_user}", status_code=303)


# Select a user to chat with
@app.get("/{username}/select/{selected_username}")
async def select_user(username: str, selected_username: str):
    if username not in users or selected_username not in users:
        raise HTTPException(status_code=404, detail="User not found")
    return RedirectResponse(f"/{username}?selected={selected_username}", status_code=303)


# Clear all notifications
@app.get("/{username}/clear_notifications")
async def clear_notifications(username: str):
    if notifications_collection is not None:
        try:
            notifications_collection.update_many(
                {"to_user": username, "read": False},
                {"$set": {"read": True}}
            )
        except Exception as e:
            logger.error(f"Error clearing notifications in MongoDB: {e}")
    else:
        notifications_storage[username] = []

    return RedirectResponse(f"/{username}", status_code=303)


# Mark specific notification as read
@app.get("/{username}/read_notification/{notification_id}")
async def read_notification(username: str, notification_id: str):
    if notifications_collection is not None:
        try:
            from bson.objectid import ObjectId
            notifications_collection.update_one(
                {"_id": ObjectId(notification_id), "to_user": username},
                {"$set": {"read": True}}
            )
        except Exception as e:
            logger.error(f"Error marking notification as read in MongoDB: {e}")
    else:
        # For in-memory storage, remove the notification
        notifications_storage[username] = [
            notif for notif in notifications_storage.get(username, [])
            if notif.get('id') != notification_id
        ]

    return RedirectResponse(f"/{username}", status_code=303)


@app.on_event("shutdown")
def shutdown_event():
    if client:
        client.close()
        logger.info("✅ MongoDB connection closed")


# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)