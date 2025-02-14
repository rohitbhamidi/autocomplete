from flask import Flask, request, jsonify, render_template
import singlestoredb as s2

app = Flask(__name__)

def get_connection():
    """
    Establish a connection to your SingleStore cloud instance.
    Replace these placeholders with your actual credentials.
    """
    return s2.connect(
        host='your-singlestore-host',
        user='your-singlesotre-user',
        password='your-singlestore-password',
        database='your-singlestore-database'
    )

def setup_schema():
    """
    1. Drops any existing 'products' table.
    2. Creates a 'products' table with an n-gram FULLTEXT index (Version 2).
       - minGramSize=2, maxGramSize=5
       - lower_case token filter
    3. Inserts sample data and flushes the index.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DROP TABLE IF EXISTS products;")
    create_table_query = """
    CREATE TABLE products (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(255),
        FULLTEXT USING VERSION 2 (name)
            INDEX_OPTIONS '{
                "analyzer": {
                    "custom": {
                        "tokenizer": {
                            "n_gram": {
                                "minGramSize": 2,
                                "maxGramSize": 5
                            }
                        },
                        "token_filters": ["lower_case"]
                    }
                }
            }'
    );
    """
    cursor.execute(create_table_query)

    # Sample data
    sample_products = [
        "iphone", "ipod", "ipad",
        "samsung", "nokia", "motorola",
        "pixel", "blackberry", "htc"
    ]
    insert_query = "INSERT INTO products (name) VALUES (%s)"
    for product in sample_products:
        cursor.execute(insert_query, (product,))
    conn.commit()

    # Force the FULLTEXT index to refresh
    cursor.execute("OPTIMIZE TABLE products FLUSH;")
    cursor.close()
    conn.close()
    print("Schema setup and sample data population complete.")

def get_autocomplete_suggestions(user_input):
    """
    Returns autocomplete suggestions by combining:
      1. N-gram prefix search (BM25 too, but used in a prefix expression).
      2. If few matches, a fuzzy search (~1) with BM25 for ranking.
    
    Importantly, we do NOT use MATCH(...) AGAINST(...) because we want to
    avoid the syntax errors with BM25 + fuzzy + n-gram. Instead, we directly
    use BM25(table_name, 'search_expression').
    
    For prefix matching with BM25, we can still specify 'name:ip*' or 'name:ip*'?
    However, SingleStore doesn't support a leading wildcard. We'll do something
    simpler: just check for any tokens that contain user_input (for an example).
    
    (Alternatively, we can just do a standard BM25 with your typed input and
    let the n-gram index handle it as a partial match.)
    """
    conn = get_connection()
    cursor = conn.cursor()

    suggestions = []

    # Always do a normal n-gram BM25 search
    prefix_expr = f"name:{user_input}"
    prefix_query = f"""
        SELECT name, BM25(products, '{prefix_expr}') AS score
        FROM products
        WHERE BM25(products, '{prefix_expr}') > 0
        ORDER BY score DESC
        LIMIT 10;
    """
    cursor.execute(prefix_query)
    for (name, _) in cursor.fetchall():
        suggestions.append(name)

    # If fewer than 5 suggestions and user_input >= 4 chars, do fuzzy
    if len(suggestions) < 5 and len(user_input) >= 4:
        fuzzy_expr = f"name:{user_input}~1"
        fuzzy_query = f"""
            SELECT name, BM25(products, '{fuzzy_expr}') AS score
            FROM products
            WHERE BM25(products, '{fuzzy_expr}') > 0
            ORDER BY score DESC
            LIMIT 10;
        """
        cursor.execute(fuzzy_query)
        for (name, _) in cursor.fetchall():
            if name not in suggestions:
                suggestions.append(name)

    cursor.close()
    conn.close()
    return suggestions

@app.route('/')
def index():
    """Renders a simple page with an input box."""
    return render_template('index.html')

@app.route('/autocomplete')
def autocomplete():
    term = request.args.get('term', '')
    suggestions = get_autocomplete_suggestions(term)
    # Just return the top suggestion if it starts with the term (case-insensitive).
    best = ""
    if suggestions:
        best_candidate = suggestions[0]
        if best_candidate.lower().startswith(term.lower()):
            best = best_candidate
    return jsonify({"suggestion": best})

if __name__ == '__main__':
    setup_schema()
    app.run(debug=True)
