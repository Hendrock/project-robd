from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
import dash
from dash import dash_table, dcc, html, Input, Output, State
import pandas as pd
import uvicorn
import requests

# Database Setup
mongo_client = MongoClient("mongodb://admin:password@localhost:27017")
mongo_db = mongo_client["movie_db"]
movies_col = mongo_db["movies"]
ratings_col = mongo_db["movie_ratings_summary"]

ratings_data = {
    doc["_id"]: {
        "avg_rating": doc.get("avg_rating"),
        "rating_count": doc.get("rating_count")
    }
    for doc in ratings_col.find({}, {"_id": 1, "avg_rating": 1, "rating_count": 1})
}

# FastAPI App (CRUD Endpoints)
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Welcome to the Movie API. Try /movies_with_ratings"}

@app.get("/movies_with_ratings")
def get_movies():
    movies = list(movies_col.find({}, {"_id": 1, "title": 1, "year": 1, "genres": 1}))
    result = []
    for movie in movies:
        rating_info = ratings_data.get(movie["_id"], {"avg_rating": None, "rating_count": 0})
        result.append({
            "movieId": movie["_id"],
            "title": movie.get("title"),
            "year": movie.get("year"),
            "genres": ", ".join(movie.get("genres", [])),
            "avg_rating": rating_info["avg_rating"],
            "rating_count": rating_info["rating_count"]
        })
    return result

@app.post("/mongo/movies")
def create_movie(movie: dict):
    if movies_col.find_one({"_id": movie.get("movieId")}):
        raise HTTPException(status_code=400, detail="Movie with this _id already exists")

    movie["_id"] = movie.pop("movieId")

    # Defaults for year and genres
    movie["year"] = movie.get("year", "9999")

    genres = movie.get("genres")
    if not genres:
        movie["genres"] = ["(no genres listed)"]
    elif isinstance(genres, str):
        movie["genres"] = [g.strip() for g in genres.split(",") if g.strip()]
        if not movie["genres"]:
            movie["genres"] = ["(no genres listed)"]

    result = movies_col.insert_one(movie)

    # Insert default rating document if it doesn't exist
    if not ratings_col.find_one({"_id": movie["_id"]}):
        ratings_col.insert_one({
            "_id": movie["_id"],
            "avg_rating": 0.0,
            "rating_count": 0
        })

    return {
        "id": str(result.inserted_id),
        "avg_rating": 0.0,
        "rating_count": 0
    }

@app.get("/mongo/movies/{movie_id}")
def read_movie(movie_id: int):
    movie = movies_col.find_one({"_id": movie_id}, {"_id": 0})
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")
    return movie

@app.put("/mongo/movies/{movie_id}")
def update_movie(movie_id: int, updates: dict):
    updates.pop("movieId", None)

    # Normalize year and genres with default
    if "year" in updates and not updates["year"]:
        updates["year"] = "9999"

    if "genres" in updates:
        if isinstance(updates["genres"], str):
            genres = [g.strip() for g in updates["genres"].split(",") if g.strip()]
            updates["genres"] = genres if genres else ["(no genres listed)"]
        elif not updates["genres"]:
            updates["genres"] = ["(no genres listed)"]

    result = movies_col.update_one({"_id": movie_id}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Movie not found")
    return {"status": "updated"}

@app.delete("/mongo/movies/{movie_id}")
def delete_movie(movie_id: int):
    result = movies_col.delete_one({"_id": movie_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Movie not found")
    return {"status": "deleted"}

# Dash Dashboard (Simplified)
dash_app = dash.Dash(__name__)

dash_app.layout = html.Div([
    html.H1("Movie Ratings Dashboard"),
    dcc.Store(id="movie-data-store"),
    dcc.Store(id="highlight-movie-id"),
    dcc.Loading(type="circle"),
    html.Br(),
    html.Div(id="ratings-table"),
    html.Div([
        html.H3("MongoDB CRUD Operations"),
        dcc.Input(id="mongo-movie-id", type="number", placeholder="Movie ID"),
        dcc.Input(id="mongo-title", placeholder="Title"),
        dcc.Input(id="mongo-year", placeholder="Year of Release"),
        dcc.Input(id="mongo-genres", placeholder="Genres (comma-separated)"),
        html.Button("Create/Update", id="mongo-submit"),
        html.Button("Read", id="mongo-read"),
        html.Button("Delete", id="mongo-delete"),
        html.Div(id="mongo-response", style={"marginTop": "10px", "whiteSpace": "pre-wrap"})
    ])
])

@dash_app.callback(
    Output("ratings-table", "children"),
    Input("mongo-submit", "n_clicks"),
    Input("mongo-read", "n_clicks"),
    Input("mongo-delete", "n_clicks"),
    Input("highlight-movie-id", "data")
)
def update_table(*args):
    highlight_movie_id = args[-1]
    response = requests.get("http://localhost:8000/movies_with_ratings")
    df = pd.DataFrame(response.json())
    if df.empty:
        return html.Div("No data available.")
    if "movieId" in df.columns:
        df = df.sort_values(by="movieId", ascending=True)
    columns = [
        {"name": "Movie ID", "id": "movieId"},
        {"name": "Title", "id": "title"},
        {"name": "Year", "id": "year"},
        {"name": "Genres", "id": "genres"},
        {"name": "Avg. Rating", "id": "avg_rating"},
        {"name": "Rating Count", "id": "rating_count"}
    ]
    style_data_conditional = []
    if highlight_movie_id and "movieId" in df.columns:
        style_data_conditional.append({
            "if": {"filter_query": f"{{movieId}} = {highlight_movie_id}"},
            "backgroundColor": "#ffe082",
            "fontWeight": "bold"
        })
    return dash_table.DataTable(
        columns=columns,
        data=df.to_dict("records"),
        style_table={"overflowX": "auto"},
        style_cell={"textAlign": "left"},
        style_header={"fontWeight": "bold"},
        style_data_conditional=style_data_conditional,
        page_size=10
    )

@dash_app.callback(
    Output("mongo-response", "children"),
    Output("highlight-movie-id", "data"),
    Input("mongo-submit", "n_clicks"),
    Input("mongo-read", "n_clicks"),
    Input("mongo-delete", "n_clicks"),
    State("mongo-movie-id", "value"),
    State("mongo-title", "value"),
    State("mongo-year", "value"),
    State("mongo-genres", "value"),
    prevent_initial_call=True
)
def handle_mongo_crud(create_clicks, read_clicks, delete_clicks, movie_id, title, year, genres):
    ctx = dash.callback_context
    if not ctx.triggered:
        return "No action taken.", None
    action = ctx.triggered[0]["prop_id"].split(".")[0]
    if not movie_id:
        return "Movie ID is required.", None
    if action == "mongo-submit":
        updates = {}
        if title: updates["title"] = title
        if year: updates["year"] = year
        if genres: updates["genres"] = [g.strip() for g in genres.split(",")]
        if updates:
            resp = requests.put(f"http://localhost:8000/mongo/movies/{movie_id}", json=updates)
            if resp.status_code == 404:
                movie = {"movieId": movie_id}
                if title: movie["title"] = title
                if year: movie["year"] = year
                if genres: movie["genres"] = [g.strip() for g in genres.split(",")]
                resp = requests.post("http://localhost:8000/mongo/movies", json=movie)
                return f"Movie created.\n{resp.json()}", movie_id
            return f"Movie updated.\n{resp.json()}", movie_id
        else:
            return "No fields to update.", None
    elif action == "mongo-read":
        resp = requests.get(f"http://localhost:8000/mongo/movies/{movie_id}")
        if resp.status_code == 200:
            return f"Movie found:\n{resp.json()}", movie_id
        return "Movie not found.", None
    elif action == "mongo-delete":
        resp = requests.delete(f"http://localhost:8000/mongo/movies/{movie_id}")
        return (f"Delete status: {resp.json()}" if resp.status_code == 200 else "Movie not found."), None
    return "Unhandled operation.", None

# Main Execution
if __name__ == "__main__":
    import threading
    threading.Thread(
        target=uvicorn.run,
        kwargs={"app": app, "host": "127.0.0.1", "port": 8000},
        daemon=True
    ).start()
    dash_app.run(host="127.0.0.1", port=8050)
