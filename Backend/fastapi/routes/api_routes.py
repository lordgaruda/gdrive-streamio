import asyncio
import json
from fastapi import Request, Query, HTTPException
from fastapi.responses import StreamingResponse
from Backend import db, StartTime, __version__
from Backend.logger import LOGGER
from Backend.helper.pyro import get_readable_time
from Backend.helper.metadata import (
    search_movie_candidates,
    search_tv_candidates,
    fetch_selected_movie_metadata,
    fetch_selected_tv_metadata,
)
from Backend.pyrofork.bot import StreamBot
from time import time


# --- API Routes for System Stats ---

async def get_system_stats_api():
    try:
        db_stats = await db.get_database_stats()
        total_movies = sum(stat.get("movie_count", 0) for stat in db_stats)
        total_tv_shows = sum(stat.get("tv_count", 0) for stat in db_stats)
        api_tokens = await db.get_all_api_tokens()
        has_gdrive = await db.load_gdrive_token() is not None
        
        return {
            "server_status": "running",
            "uptime": get_readable_time(time() - StartTime),
            "telegram_bot": f"@{StreamBot.username}" if StreamBot and StreamBot.username else "@StreamBot",
            "gdrive_connected": has_gdrive,
            "version": __version__,
            "movies": total_movies,
            "tv_shows": total_tv_shows,
            "databases": db_stats,
            "total_databases": len(db_stats),
            "current_db_index": db.current_db_index,
            "api_tokens": api_tokens
        }
    except Exception as e:
        print(f"System Stats API Error: {e}")
        return {
            "server_status": "error", 
            "error": str(e)
        }
    
# --- API Routes for Media Management ---

async def list_media_api(
    media_type: str = Query("movie", regex="^(movie|tv)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    search: str = Query("", max_length=100)
):
    try:
        if search:
            result = await db.search_documents(search, page, page_size)
            filtered_results = [item for item in result['results'] if item.get('media_type') == media_type]
            total_filtered = len(filtered_results)
            start_index = (page - 1) * page_size
            end_index = start_index + page_size
            paged_results = filtered_results[start_index:end_index]
            
            return {
                "total_count": total_filtered,
                "current_page": page,
                "total_pages": (total_filtered + page_size - 1) // page_size,
                "movies" if media_type == "movie" else "tv_shows": paged_results
            }
        else:
            if media_type == "movie":
                return await db.sort_movies([], page, page_size)
            else:
                return await db.sort_tv_shows([], page, page_size)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def delete_media_api(
    tmdb_id: int,
    db_index: int,
    media_type: str = Query(regex="^(movie|tv)$")
):
    try:
        media_type_formatted = "Movie" if media_type == "movie" else "Series"
        result = await db.delete_document(media_type_formatted, tmdb_id, db_index)
        if result:
            return {"message": "Media deleted successfully"}
        else:
            raise HTTPException(status_code=404, detail="Media not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def update_media_api(
    request: Request,
    tmdb_id: int,
    db_index: int,
    media_type: str = Query(regex="^(movie|tv)$")
):
    try:
        update_data = await request.json()
        if 'rating' in update_data and update_data['rating']:
            try:
                update_data['rating'] = float(update_data['rating'])
            except (ValueError, TypeError):
                update_data['rating'] = 0.0
        
        if 'release_year' in update_data and update_data['release_year']:
            try:
                update_data['release_year'] = int(update_data['release_year'])
            except (ValueError, TypeError):
                pass
        if 'genres' in update_data:
            if isinstance(update_data['genres'], str):
                update_data['genres'] = [g.strip() for g in update_data['genres'].split(',') if g.strip()]
            elif not isinstance(update_data['genres'], list):
                update_data['genres'] = []
        
        if 'languages' in update_data:
            if isinstance(update_data['languages'], str):
                update_data['languages'] = [l.strip() for l in update_data['languages'].split(',') if l.strip()]
            elif not isinstance(update_data['languages'], list):
                update_data['languages'] = []
        if media_type == "movie":
            if 'runtime' in update_data and update_data['runtime']:
                try:
                    update_data['runtime'] = int(update_data['runtime'])
                except (ValueError, TypeError):
                    pass
        elif media_type == "tv":
            if 'total_seasons' in update_data and update_data['total_seasons']:
                try:
                    update_data['total_seasons'] = int(update_data['total_seasons'])
                except (ValueError, TypeError):
                    pass
            
            if 'total_episodes' in update_data and update_data['total_episodes']:
                try:
                    update_data['total_episodes'] = int(update_data['total_episodes'])
                except (ValueError, TypeError):
                    pass
        update_data = {k: v for k, v in update_data.items() if v != ""}
        result = await db.update_document(media_type, tmdb_id, db_index, update_data)
        if result:
            return {"message": "Media updated successfully"}
        else:
            raise HTTPException(status_code=404, detail="Media not found or no changes made")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def get_media_details_api(
    tmdb_id: int,
    db_index: int,
    media_type: str = Query(regex="^(movie|tv)$")
):
    try:
        result = await db.get_document(media_type, tmdb_id, db_index)
        if result:
            return result
        else:
            raise HTTPException(status_code=404, detail="Media not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def delete_movie_quality_api(tmdb_id: int, db_index: int, id: str):
    try:
        result = await db.delete_movie_quality(tmdb_id, db_index, id)
        if result:
            return {"message": "Quality deleted successfully"}
        else:
            raise HTTPException(status_code=404, detail="Quality not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def delete_tv_quality_api(
    tmdb_id: int, db_index: int, season: int, episode: int, id: str
):
    try:
        result = await db.delete_tv_quality(tmdb_id, db_index, season, episode, id)
        if result:
            return {"message": "deleted successfully"}
        else:
            raise HTTPException(status_code=404, detail="Quality not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def delete_tv_episode_api(
    tmdb_id: int, db_index: int, season: int, episode: int
):
    try:
        result = await db.delete_tv_episode(tmdb_id, db_index, season, episode)
        if result:
            return {"message": "Episode deleted successfully"}
        else:
            raise HTTPException(status_code=404, detail="Episode not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def delete_tv_season_api(tmdb_id: int, db_index: int, season: int):
    try:
        result = await db.delete_tv_season(tmdb_id, db_index, season)
        if result:
            return {"message": "Season deleted successfully"}
        else:
            raise HTTPException(status_code=404, detail="Season not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- API Routes for Token Management ---

async def create_token_api(payload: dict):
    try:
        token_name = payload.get("name")
        daily_limit = payload.get("daily_limit_gb")
        monthly_limit = payload.get("monthly_limit_gb")
        
        if not token_name:
             raise HTTPException(status_code=400, detail="Token name is required")
        def parse_limit(val):
            try:
                v = float(val)
                return v if v > 0 else None
            except (ValueError, TypeError):
                return None

        new_token = await db.add_api_token(
            token_name, 
            parse_limit(daily_limit), 
            parse_limit(monthly_limit)
        )
        return new_token
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def update_token_limits_api(token: str, payload: dict):
    try:
        daily_limit = payload.get("daily_limit_gb")
        monthly_limit = payload.get("monthly_limit_gb")
        
        def parse_limit(val):
            try:
                v = float(val)
                return v if v > 0 else None
            except (ValueError, TypeError, AttributeError):
                return None

        result = await db.update_api_token_limits(
            token,
            parse_limit(daily_limit),
            parse_limit(monthly_limit)
        )
        
        if result:
            return {"message": "Limits updated successfully"}
        else:
            return {"message": "Limits updated successfully"}
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def revoke_token_api(token: str):
    try:
        result = await db.revoke_api_token(token)
        if result:
            return {"message": "Token revoked successfully"}
        else:
            raise HTTPException(status_code=404, detail="Token not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



# --- Speed Test API (removed — not applicable in GDrive mode) ---

async def speed_test_api(*args, **kwargs):
    raise HTTPException(status_code=410, detail="Speed test not available in GDrive mode")

async def speed_test_stream_api(*args, **kwargs):
    raise HTTPException(status_code=410, detail="Speed test not available in GDrive mode")


# ---------------------------------------------------------------------------
# Admin API Routes
# ---------------------------------------------------------------------------

async def get_admin_stats_api() -> dict:
    has_gdrive = await db.load_gdrive_token() is not None
    return {
        "gdrive_connected": has_gdrive,
        "movies": await db.count_movies(),
        "tv_shows": await db.count_shows(),
    }

async def clear_cache_api() -> dict:
    return {"status": "success", "message": "No cache to clear (GDrive mode)."}

async def get_dead_links_api() -> dict:
    from Backend import db
    try:
        dead_links = await db.get_all_dead_links()
        return {"status": "success", "data": dead_links}
    except Exception as e:
        return {"status": "error", "message": str(e)}

async def get_stream_analytics_api() -> dict:
    from Backend import db
    try:
        data = await db.get_stream_analytics(limit=200)
        return {"status": "success", "data": data}
    except Exception as e:
        from Backend.logger import LOGGER
        LOGGER.error(f"Stream analytics API error: {e}")
        return {"status": "error", "message": str(e)}

async def clear_stream_analytics_api() -> dict:
    try:
        result = await db.dbs["tracking"]["stream_analytics"].delete_many({})
        LOGGER.info(f"Admin cleared stream analytics ({result.deleted_count} records deleted).")

        return {
            "status": "success",
            "message": f"{result.deleted_count} analytics records cleared."
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ---------------------------------------------------------------------------
# Admin Subscription Management API Routes
# ---------------------------------------------------------------------------

async def get_subscription_plans_api() -> dict:
    from Backend import db
    try:
        plans = await db.get_subscription_plans()
        return {"status": "success", "data": plans}
    except Exception as e:
        return {"status": "error", "message": str(e)}

async def add_subscription_plan_api(payload: dict) -> dict:
    from Backend import db
    try:
        days = int(payload.get("days", 0))
        price = float(payload.get("price", 0.0))
        if days <= 0 or price < 0:
            raise HTTPException(status_code=400, detail="Invalid plan parameters")
            
        plan_id = await db.add_subscription_plan(days, price)
        if plan_id:
            return {"status": "success", "message": "Plan added successfully", "plan_id": plan_id}
        else:
            raise HTTPException(status_code=500, detail="Failed to add plan")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def update_subscription_plan_api(plan_id: str, payload: dict) -> dict:
    from Backend import db
    try:
        days = int(payload.get("days", 0))
        price = float(payload.get("price", 0.0))
        if days <= 0 or price < 0:
             raise HTTPException(status_code=400, detail="Invalid plan parameters")
             
        success = await db.update_subscription_plan(plan_id, days, price)
        if success:
             return {"status": "success", "message": "Plan updated successfully"}
        else:
             raise HTTPException(status_code=404, detail="Plan not found or update failed")
    except HTTPException:
         raise
    except Exception as e:
         raise HTTPException(status_code=500, detail=str(e))

async def delete_subscription_plan_api(plan_id: str) -> dict:
    from Backend import db
    try:
        success = await db.delete_subscription_plan(plan_id)
        if success:
            return {"status": "success", "message": "Plan deleted successfully"}
        else:
            raise HTTPException(status_code=404, detail="Plan not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def get_all_subscribers_api() -> dict:
    from Backend import db
    try:
        users = await db.get_all_subscribers()
        return {"status": "success", "data": users}
    except Exception as e:
        return {"status": "error", "message": str(e)}

async def manage_subscriber_api(user_id: int, payload: dict) -> dict:
    from Backend import db
    try:
        action = payload.get("action")
        days = int(payload.get("days", 0))
        
        if action not in ["extend", "reduce", "delete"]:
            raise HTTPException(status_code=400, detail="Invalid action")
            
        success = await db.manage_subscriber(user_id, action, days)
        if success:
            return {"status": "success", "message": "User subscription updated successfully"}
        else:
            raise HTTPException(status_code=404, detail="User not found or update failed")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Access Management API ---

async def get_all_tokens_api() -> dict:
    from Backend import db
    from Backend.config import Telegram
    from datetime import datetime
    try:
        tokens = await db.get_all_api_tokens()
        now = datetime.utcnow()
        result = []

        # Pre-load all subscribers into a dict keyed by user_id for O(1) lookup
        subscriber_map = {}       # user_id (str) -> user doc
        if Telegram.SUBSCRIPTION:
            try:
                for u in await db.get_all_subscribers():
                    uid = str(u.get("_id"))
                    subscriber_map[uid] = u
            except Exception:
                pass

        def display_name(user, user_id, token_name=None):
            """Return a non-empty display name for a user."""
            if user:
                n = user.get("first_name") or user.get("username")
                if n:
                    return n
            # Fall back to the name stored on the token itself (set at creation time)
            if token_name:
                return token_name
            return f"User {user_id}" if user_id else "Telegram User"

        def build_entry(user_id, user, token_doc):
            """Build a unified access entry from optional user + token records."""
            expiry = None
            sub_status = None
            user_found = bool(user)

            if user:
                sub_status = user.get("subscription_status")
                expiry = user.get("subscription_expiry")

            # Token-level expiry as fallback
            if token_doc:
                t_expiry = token_doc.get("subscription_expiry") or token_doc.get("expires_at")
                if t_expiry and not expiry:
                    expiry = t_expiry

            # Determine status
            if Telegram.SUBSCRIPTION:
                if not user_found:
                    is_expired = True
                elif sub_status != "active":
                    is_expired = True
                elif not expiry:
                    is_expired = True
                else:
                    is_expired = expiry < now
            else:
                is_expired = bool(expiry and expiry < now)

            token_str = token_doc.get("token") if token_doc else None
            created = token_doc.get("created_at") if token_doc else (user.get("created_at") if user else None)

            return {
                "token": token_str,
                "user_id": user_id,
                "user_name": display_name(user, user_id, token_doc.get("name") if token_doc else None),
                "user_found": user_found,
                "has_token": bool(token_str),
                "created_at": created.isoformat() if created else None,
                "expires_at": expiry.isoformat() if expiry else None,
                "is_expired": is_expired,
                "sub_status": sub_status,
                "addon_url": (
                    f"{Telegram.BASE_URL}/stremio/{token_str}/manifest.json"
                    if token_str else None
                ),
            }

        # Track user_ids that are already represented via a token row
        seen_user_ids = set()

        # --- 1. Process all existing tokens ---
        for t in tokens:
            token_user_id = t.get("user_id")

            # Try to resolve user from subscriber_map using token's user_id
            user = None
            if token_user_id:
                uid_str = str(token_user_id)
                user = subscriber_map.get(uid_str)
                if not user:
                    # Fallback: query DB if not in subscriber_map (e.g. non-active subscribers)
                    try:
                        user = await db.get_user(int(token_user_id))
                    except Exception:
                        pass
                seen_user_ids.add(uid_str)

            result.append(build_entry(token_user_id, user, t))

        # --- 2. Add subscribers who have NO token ---
        for uid_str, u in subscriber_map.items():
            if uid_str in seen_user_ids:
                continue  # already covered by a token row
            result.append(build_entry(u.get("_id"), u, None))

        # Sort: active-with-token first, then active-no-token, expired last
        result.sort(key=lambda x: (x["is_expired"], not x["has_token"]))
        return {"tokens": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def revoke_token_api(token: str) -> dict:
    from Backend import db
    try:
        success = await db.revoke_api_token(token)
        if success:
            return {"status": "success", "message": "Token revoked."}
        raise HTTPException(status_code=404, detail="Token not found.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def assign_plan_api(user_id: int, days: int) -> dict:
    """Assign (or extend) a subscription for any user by user_id, even if not in DB."""
    from Backend import db
    try:
        if days < 1:
            raise HTTPException(status_code=400, detail="Days must be at least 1.")
        result = await db.assign_subscription(user_id, days)
        return {"status": "success", "data": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def link_token_user_api(token: str, user_id: int) -> dict:
    """Link an orphan token (no user_id) to a Telegram user_id."""
    from Backend import db
    try:
        success = await db.link_token_user(token, user_id)
        if success:
            return {"status": "success", "message": f"Token linked to user {user_id}."}
        raise HTTPException(status_code=404, detail="Token not found or already linked.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




async def search_media_rescan_api(media_type: str, query: str, year: int | None = None):
    query = (query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required.")

    if media_type == "movie":
        results = await search_movie_candidates(query=query, year=year)
    elif media_type == "tv":
        results = await search_tv_candidates(query=query)
    else:
        raise HTTPException(status_code=400, detail="Invalid media_type.")

    return {"results": results}


async def apply_media_rescan_api(request: Request, tmdb_id: int, db_index: int, media_type: str):
    body = await request.json()
    selected_id = str(body.get("selected_id") or "").strip()

    if not selected_id:
        raise HTTPException(status_code=400, detail="selected_id is required.")

    current_doc = await db.get_document(media_type, tmdb_id, db_index)
    if not current_doc:
        raise HTTPException(status_code=404, detail="Media not found.")

    if media_type == "movie":
        metadata = await fetch_selected_movie_metadata(selected_id)
    elif media_type == "tv":
        metadata = await fetch_selected_tv_metadata(selected_id)
    else:
        raise HTTPException(status_code=400, detail="Invalid media_type.")

    if not metadata:
        raise HTTPException(status_code=404, detail="Unable to fetch metadata for selected item.")

    updated_doc = await db.replace_media_metadata(
        media_type=media_type,
        tmdb_id=tmdb_id,
        db_index=db_index,
        metadata=metadata,
    )

    if not updated_doc:
        raise HTTPException(status_code=500, detail="Failed to replace media metadata.")

    return {
        "success": True,
        "message": "Metadata rescanned successfully.",
        "redirect_tmdb_id": updated_doc.get("tmdb_id"),
        "db_index": updated_doc.get("db_index", db_index),
        "media_type": media_type,
        "data": updated_doc,
}
