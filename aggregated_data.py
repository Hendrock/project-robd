import json
from cassandra.cluster import Cluster
from collections import defaultdict

# Connect to Cassandra and keyspace
cluster = Cluster(['127.0.0.1'])
session = cluster.connect('movie')

# Query the ratings
rows = session.execute('SELECT movieId, rating FROM reviews')

# Aggregate ratings
ratings_summary = defaultdict(lambda: {"count": 0, "sum": 0.0})

for row in rows:
    ratings_summary[row.movieid]["count"] += 1
    ratings_summary[row.movieid]["sum"] += row.rating

# Compute averages and store in a list of dicts
aggregated_data = []
for movieid, data in ratings_summary.items():
    avg_rating = data["sum"] / data["count"]
    aggregated_data.append({
        "_id": movieid,
        "avg_rating": round(avg_rating, 2),  # round for better readability
        "rating_count": data["count"]
    })

# ✅ Save to a JSON file
with open("aggregated_ratings.json", "w", encoding="utf-8") as f:
    json.dump(aggregated_data, f, indent=2)

print("Aggregated ratings saved to 'aggregated_ratings.json'")