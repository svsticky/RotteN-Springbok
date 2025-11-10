import os
import pandas as pd
import datetime
from flask import Flask, redirect, url_for, session, request, render_template, flash
from authlib.integrations.flask_client import OAuth
from werkzeug.utils import secure_filename
import uuid
import time
from functools import wraps

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads/'
app.config['RESULTS_FOLDER'] = 'results/'  # Add a results folder

app.secret_key = os.getenv('SECRET_KEY')
app.config["OAUTH_CLIENT_ID"] = os.getenv("OAUTH_CLIENT_ID", "client-id")
app.config["OAUTH_CLIENT_SECRET"] = os.getenv("OAUTH_CLIENT_SECRET", "client-secret")
app.config["OAUTH_REDIRECT_URI"] = os.getenv("OAUTH_REDIRECT_URL", "http://localhost:5000/auth/callback")
app.config["OAUTH_AUTHORIZE_URL"] = os.getenv("OAUTH_AUTHORIZE_URL", "https://example.com/oauth/authorize")
app.config["OAUTH_TOKEN_URL"] = os.getenv("OAUTH_TOKEN_URL", "https://example.com/oauth/token")
app.config["OAUTH_API_BASE_URL"] = os.getenv("OAUTH_API_BASE_URL", "https://example.com/api/")

oauth = OAuth(app)
auth_provider = oauth.register(
    name="custom_oauth",
    client_id=app.config["OAUTH_CLIENT_ID"],
    client_secret=app.config["OAUTH_CLIENT_SECRET"],
    access_token_url=app.config["OAUTH_TOKEN_URL"],
    authorize_url=app.config["OAUTH_AUTHORIZE_URL"],
    api_base_url=app.config["OAUTH_API_BASE_URL"],
    client_kwargs={"scope": "profile"},
)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

# Allowed file extensions -> only allow csv
ALLOWED_EXTENSIONS = {'csv'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def cleanup_old_results(days=1):
    """Remove files older than 'days' from the results folder."""
    folder = app.config['RESULTS_FOLDER']
    if not os.path.exists(folder):
        return
    
    now = time.time()
    cutoff = now - days * 24 * 60 * 60  # Seconds in a day

    for filename in os.listdir(folder):
        filepath = os.path.join(folder, filename)
        if os.path.isfile(filepath):
            file_mtime = os.path.getmtime(filepath)
            if file_mtime < cutoff:
                try:
                    os.remove(filepath)
                    print(f"🧹 Deleted: {filename}")
                except Exception as e:
                    print(f"⚠️ Failed to delete {filename}: {e}")

def select_and_process_csv(input_csv_path, column_name="Name", n=45):
    df = pd.read_csv(input_csv_path)
    
    # Ensure the column exists
    if column_name not in df.columns:
        raise ValueError(f"Column '{column_name}' not found in the CSV file")

    # Get the list of names from the specified column
    people_list = df[column_name]

    # Ensure there are enough people to select
    if len(people_list) < n:
        raise ValueError(f"Not enough people in the list to select {n} people")

    # Randomly select 'n' people
    selected_people = people_list.sample(n=n)
    
    # Select the remaining people from the dataframe
    remaining_people = people_list[~people_list.index.isin(selected_people.index)]

    # Shuffle the remaining people
    remaining_people = remaining_people.sample(frac=1).reset_index(drop=True)
    
    # Remove the index from the selected people to prevent ordering issues
    selected_people = selected_people.reset_index(drop=True)

    return selected_people, remaining_people

def write_results_to_csv(selected_people, remaining_people, output_file_path):
    # Create a DataFrame with selected and remaining people
    results_df = pd.DataFrame({
        'Selected People': pd.Series(selected_people),
        'Remaining People': pd.Series(remaining_people)
    })

    # Write DataFrame to CSV
    results_df.to_csv(output_file_path, index=False)

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    cleanup_old_results() # Clean up old result files on each request

    if request.method == 'POST':
        # Check if the post request has the file part
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        
        file = request.files['file']
        
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)

        # Get the number of people and delay from the form
        num_people = request.form.get('num_people', type=int)
        delay_seconds = request.form.get('delay', type=int)

        # Convert delay from seconds to milliseconds for JavaScript use
        delay_ms = delay_seconds * 1000

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            try:
                # Perform the selection process with the fixed column name "Name"
                selected_people, remaining_people = select_and_process_csv(filepath, n=num_people)
                
                # Create the results directory if it doesn't exist
                if not os.path.exists(app.config['RESULTS_FOLDER']):
                    os.makedirs(app.config['RESULTS_FOLDER'])
                
                # Get current date and time to append to the filename
                now = datetime.datetime.now().strftime("%d-%m-%Y %H.%M.%S")

                # Write the results to a new CSV file
                randomGuid = uuid.uuid4()
                results_filename = f'results_{filename.rsplit(".", 1)[0]}_{now}_{randomGuid}.csv'
                results_filepath = os.path.join(app.config['RESULTS_FOLDER'], results_filename)
                write_results_to_csv(selected_people, remaining_people, results_filepath)

                # Remove the uploaded file after processing
                os.remove(filepath)

                # Render results with the filename for downloading and pass the delay in milliseconds
                return render_template('results.html', selected_people=selected_people, 
                                       remaining_people=remaining_people, 
                                       results_filename=results_filename, 
                                       delay=delay_ms)  # Pass the delay in milliseconds
            except Exception as e:
                flash(str(e))
                return redirect(request.url)
    return render_template('index.html')

@app.route("/login")
def login():
    return auth_provider.authorize_redirect(redirect_uri=app.config["OAUTH_REDIRECT_URI"])

@app.route('/download/<filename>')
@login_required
def download_file(filename):
    # Serve the CSV file from the results folder
    return send_from_directory(app.config['RESULTS_FOLDER'], filename, as_attachment=True)

@app.route("/auth/callback")
def auth_callback():
    token = auth_provider.authorize_access_token()
    try:
        resp = auth_provider.get("userinfo", token=token)
        user_info = resp.json() if resp.ok else {}
    except Exception:
        user_info = {"access_token": token.get("access_token")}

    session["user"] = user_info
    return redirect(url_for("index"))

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

if __name__ == '__main__':
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    
    app.run(debug=True)
