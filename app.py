import os
import pandas as pd
import random
import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads/'
app.config['RESULTS_FOLDER'] = 'results/'  # Add a results folder
app.secret_key = 'random_secret_key'

# Allowed file extensions -> only allow csv
ALLOWED_EXTENSIONS = {'csv'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
def index():
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
                results_filename = f'results_{filename.rsplit(".", 1)[0]}_{now}.csv'
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

@app.route('/download/<filename>')
def download_file(filename):
    # Serve the CSV file from the results folder
    return send_from_directory(app.config['RESULTS_FOLDER'], filename, as_attachment=True)

if __name__ == '__main__':
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    
    app.run(debug=True)
