import json
import sys
import os, shutil
import boto3
import collections

tempDir = '../Temp/'
infraPath = '../Templates/'

# Removes a legacy folder and files then creates it
def createFolder(path):

    # Remove the existing content and folder
    if os.path.isdir(path):
        shutil.rmtree(path)

    # Create the new folder
    try:
        os.mkdir(path)
    except OSError:
        print ("Creation of the directory %s failed\n" % path)
    else:
        print ("Successfully created the directory %s \n" % path)

# Uses a lambdaBgeneral.template and injects function config into it.
def generateFunctionTemplate(fileToCopy, fileToSave, config):

    # Creating python destination directory and .template file
    global infraPath
    functionName = os.path.splitext(fileToSave)[0]
    global tempDir

    # Open the glueTablegeneral.template generic file
    with open(fileToCopy) as json_file:
        data = json.load(json_file)

    # Load the downloaded function function.template
    with open(tempDir + functionName) as json_file:
        functionConfig = json.load(json_file)

    # Open the downloaded function.template
    # Edit the parameters, if keys exist we append to current values
    for key, value in functionConfig["LAMBDA"].items():
        if key == "Parameters":
            data["Parameters"].update(value)
        elif key == "Outputs":
            data["Outputs"].update(value)
        elif key == "Description":
            data["Parameters"]["Description"]["Default"] = value
        elif key == "Environment":
            if functionConfig["LAMBDA"]["Environment"]["Variables"]:
                for innerKey, innerValue in functionConfig["LAMBDA"]["Environment"]["Variables"].items():
                    data["Resources"]["LambdaFunction"]["Properties"]["Environment"]["Variables"][innerKey] = innerValue
        elif key == "FunctionName":
            funcName = ("${AssetGroup}-${AssetName}-%s" % value)
            data["Resources"]["LambdaFunction"]["Properties"]["FunctionName"]["Fn::Sub"] = funcName
        elif key == "MemorySize":
            data["Parameters"]["MemorySize"]["Default"] = str(value)
        elif key == "Runtime":
            data["Parameters"]["Runtime"]["Default"] = value
        elif key == "Timeout":
            data["Parameters"]["Timeout"]["Default"] = str(value)

        else:
            print("Couldn't find key %s in template" % key)

    # Save updated template to the destination file
    with open(infraPath + fileToSave + ".template", 'w') as outfile:
        json.dump(data, outfile, indent=4, sort_keys=True)

def readConfig():

    # Creating python destination directories
    global infraPath
    global tempDir
    createFolder(infraPath)
    createFolder(tempDir)

    # Take workspace as parameter or set current directory
    if len(sys.argv) >= 2:
        path = sys.argv[1]
    else:
        path = "."
    print("Using this properties file: %s\n" % path)

    # Read JSON configurations file
    with open(path + "/glueProperties.json") as f:
        config = json.load(f)

    DBSourceTemplate = config["DEFAULT"]["targetDB"]
    DBtoGenerate = config["DEFAULT"]["sourceDB"]

    return config, DBSourceTemplate, DBtoGenerate

def deployFunctions(SourceTemplate, toGenerate, config):
    for entry in toGenerate:
        generateFunctionTemplate(SourceTemplate, entry + "_SourceFunction", config)



# Removes a list of keys from the Lambda JSON
def cleanFunctionConfig(data):
    listOfRemovalKeys = ["CodeSha256", "Handler", "CodeSize", "Role", "FunctionArn", "LastModified", "RevisionId", "TracingConfig", "Version"]
    for key in listOfRemovalKeys:
        if key in data["LAMBDA"]:
            data["LAMBDA"].pop(key, None) # If key exist remove it and return it's value
    return data

# Gets an array of function names and request the function deployment package and configuration
def parseFunctions(functions, toGenerate):
    global tempDir

    # Generate Glue JSON, set into Temp folder
    for function in functions:
        functionName = function["FunctionName"]
        if any(functionName in s for s in toGenerate):
            print("Working on function: %s\n" % functionName)

            # Save function original parameters into the databaseName in Temp location
            with open( tempDir + functionName + '_SourceFunction', 'w' ) as outfile:
                print("Writing: %s to a JSON file in Inputs\n" % functionName)
                data = {'LAMBDA': function}
                data = cleanFunctionConfig(data)
                print (json.dumps(data, indent=4, sort_keys=True) + "\n")
                json.dump(data, outfile, indent=4, sort_keys=True)


# Gets a list of lambda function from environment, it's required to update keys
def getFunctions(client, toGenerate):
    data = []
    response = client.list_functions()

    # Iterate until all functions is acquired, limited to 50 per iteration
    if "NextMarker" in response:
        # Create a reusable Paginator
        paginator = client.get_paginator('list_functions')

        # Create a PageIterator from the Paginator
        func_iterator = paginator.paginate()

        for page in func_iterator:
            data.extend(page['Functions'])

    data.extend(response["Functions"])

    parseFunctions(data, toGenerate)

def generateSchemaDict():
    # Open the keys file and parse line by line, dump into json output file
    data = []
    counter = 0
    with open("columns", "r") as file:
        for line in file:
            keyPair = line.replace(',', '').replace('`', '').strip().split(' ')
            entry = collections.OrderedDict()
            entry["Type"] = keyPair[1]
            entry["Name"] = keyPair[0]
            data.append(entry)
    print("Found %d new entries\n" % len(data))

    # Save resulted JSON to a file
    with open("columns-output", 'w') as outfile:
        # print json.dumps(data, indent=4, sort_keys=True) + "\n"
        json.dump(data, outfile, indent=4, sort_keys=True)

def main():
    # Before running, check properties.ini, Insert wanted function names as list
    config, lambdaSourceTemplate, lambdatoGenerate = readConfig()

    # Make sure you have valid credentials, also make sure they are temporary and restricted in time
    # You can use Security Token Service to get a temporary token, it follows the best practice
    session = boto3.Session()
    region = session.region_name
    print("Currently using %s as the region" % region)
    if(region is None):
        print("ERROR: Make sure to set the region")
    credentials = session.get_credentials()
    current_credentials = credentials.get_frozen_credentials()

    client = boto3.client('lambda',
                          aws_access_key_id=current_credentials.access_key,
                          aws_secret_access_key=current_credentials.secret_key,
                          aws_session_token=current_credentials.token
                          )

    # Step 1, get the database config and files
    getFunctions(client, lambdatoGenerate)


    # Step 2, set the deployment folders and inject parameters to lambdaGeneral.template
    deployFunctions(lambdaSourceTemplate, lambdatoGenerate, config)
    createFolder(tempDir)  # Clean Temp directory

# Entry point
main()
# generateSchemaDict()