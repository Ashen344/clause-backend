def get_or_create_user(clerk_id: str, email: str, full_name: str) -> dict:
    existing = users_collection.find_one({"clerk_id": clerk_id})  # L17

    if existing:                                                     # L19 ← BRANCH
        users_collection.update_one(                                # L21
            {"_id": existing["_id"]},
            {"$set": {"last_login": datetime.utcnow()}}
        )
        existing["last_login"] = datetime.utcnow()                  # L24
        return user_to_response(existing)                           # L25

    new_user = {                                                     # L28
        "clerk_id": clerk_id,
        "email": email,
        "full_name": full_name,
        "role": "user",
        "organization": None,
        "status": "active",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "last_login": datetime.utcnow(),
    }
    result = users_collection.insert_one(new_user)                  # L38
    created = users_collection.find_one({"_id": result.inserted_id})# L39
    return user_to_response(created)                                # L40