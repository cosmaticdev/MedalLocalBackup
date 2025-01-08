"""
Allows a user to send their local Medal files to another local pc and have them automatically imported into the app, as a way to back up or restore medal when moving computers. 

Runs completely over local network and requires no passwords or API tokens or anything of the sort. Script must be run on both devices.
"""

try:
    import os, aiofiles, aiohttp, uvicorn, time, tarfile, requests, socket, concurrent.futures, threading, asyncio, io, json
    from tqdm import tqdm
    from fastapi import FastAPI, Request, HTTPException, Header
    from fastapi.responses import StreamingResponse, FileResponse
except:
    res = input(
        "You seem to be missing some required packages. Do you want me to install them? (Y/N)"
    )
    if res.lower() == "y" or res.lower() == "yes":
        os.system("pip install aiofiles aiohttp uvicorn requests tqdm fastapi")
        print("Please re-run this script")
        exit()
    else:
        print(
            "It's okay, I won't install them! You may encounter unexpected issues when running this program."
        )


app = FastAPI()

# define variables
global folderPath
global serverPort
global isReadyForTransfer
global isDone
folderPath = ""
serverPort = 6789
isReadyForTransfer = False
isDone = False
OUTPUT_ARCHIVE = "temp_medal_folder.tar.gz"


# checks if a device ip is running Medal
def check_device(ip):
    try:
        res = requests.get(
            f"http://{ip}:12665/api/v1/context/submit", timeout=3
        )  # check and see if Medal is actively running by pinging Medals designated port
        return ip
    except:
        return None


# gets the ip of the local machine
def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
        return local_ip
    except Exception as e:
        print(f"Error getting local IP: {e}")
        return None


# gets a range of all ips in the network and checks which ones are running Medal
def getIps():
    print("\n\nScanning network for devices running Medal...")
    devices = []
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)

    # Assume a /24 subnet
    ip_base = ".".join(local_ip.split(".")[:-1])
    ips = [f"{ip_base}.{i}" for i in range(1, 255)]

    with concurrent.futures.ThreadPoolExecutor(max_workers=75) as executor:
        results = list(executor.map(check_device, ips))

    devices = [ip for ip in results if ip is not None]

    # print out all the devices and their names
    if devices:
        pos = 1
        print("Device IPs running Medal")
        localIP = get_local_ip()
        for device in devices:
            if device == localIP:
                print(
                    f"{pos}.) "
                    + device
                    + f" ({socket.gethostbyaddr(device)[0].split('.')[0]}) [current device]"
                )
            else:
                print(
                    f"{pos}.) "
                    + device
                    + f" ({socket.gethostbyaddr(device)[0].split('.')[0]})"
                )
            pos += 1
        return devices, localIP
    else:
        print("No devices found")
        return [], localIP


# called to tell the computer to prompt the partner computer to start the upload (& subsequently downloads the data)
async def receiveFolder(ip):
    global serverPort
    global folderPath
    url = f"http://{ip}:{serverPort}/stream"
    received_size = 0

    if os.path.exists(f"{folderPath}/{OUTPUT_ARCHIVE}"):
        received_size = os.path.getsize(f"{folderPath}/{OUTPUT_ARCHIVE}")

    headers = {"Range": f"bytes={received_size}-"} if received_size > 0 else {}
    timeout = aiohttp.ClientTimeout(
        total=None, connect=None, sock_connect=None, sock_read=None
    )

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=headers) as response:
            total_size = int(response.headers.get("Content-Length", 0)) + received_size

            if response.status not in {200, 206}:
                print(
                    f"Failed to download. HTTP status {response.status}\nprogram terminating"
                )
                exit()

            with tqdm(
                initial=received_size,
                total=total_size,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
                desc="Receiving Archive",
            ) as pbar:
                async with aiofiles.open(
                    f"{folderPath}/{OUTPUT_ARCHIVE}", "ab"
                ) as output_file:
                    async for chunk in response.content.iter_chunked(1024 * 1024):
                        await output_file.write(chunk)
                        received_size += len(chunk)
                        pbar.update(len(chunk))

    # decompress the archive
    with tarfile.open(f"{folderPath}/{OUTPUT_ARCHIVE}", "r:gz") as tar:
        members = tar.getmembers()
        total_size = sum(member.size for member in members)

        with tqdm(
            total=total_size,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            desc="Extracting Archive",
        ) as pbar:
            for member in members:
                tar.extract(member, path=folderPath)
                pbar.update(member.size)

    total_size = os.path.getsize(f"{folderPath}/{OUTPUT_ARCHIVE}")

    # delete the archive once everything is extracted (dont want to waste space)
    with tqdm(
        total=total_size,
        unit="B",
        unit_scale=True,
        unit_divisor=1024,
        desc="Deleting Uneeded Archive",
    ) as pbar:
        os.remove(f"{folderPath}/{OUTPUT_ARCHIVE}")
        pbar.update(total_size)

    print("Folder received and extracted successfully!")

    # grabs the library list file to make sure clips appear correctly in the medal app. If the pc receiving the transfers already has some medal clips it will merge the two files to combine all the clip lists
    print("Getting library list file")
    try:
        with open(
            os.path.join(os.getenv("APPDATA"), "Medal", "store", "clips.json"),
            encoding="utf-8",
        ) as f:
            data = json.loads(f)
    except:
        response = requests.get(f"http://{ip}:{serverPort}/libraryList")
        with open(
            os.path.join(os.getenv("APPDATA"), "Medal", "store", "clips.json"), "wb"
        ) as f:
            f.write(response.content)
        print("Imported clips.json file")

        input("Transfer done. Click enter to terminate the program.")
        exit()
        return
    if data == None:
        data = {}
    response = json.loads(requests.get(f"http://{ip}:{serverPort}/libraryList").text)
    data.update(response)
    with open(
        os.path.join(os.getenv("APPDATA"), "Medal", "store", "clips.json"), "w"
    ) as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    print("Merged old and current clips.json files!")

    # tell the sender that everything is finished
    requests.get(f"http://{ip}:{serverPort}/finishedReceiving")

    input("Transfer done. Click enter to terminate the program.")
    exit()
    return


def getFolderSize(folder_path):
    total_size = 0
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            total_size += os.path.getsize(os.path.join(root, file))
    return total_size


# compresses the files to make transfers quicker
def compress(folder_path, start_byte=0):
    buffer = io.BytesIO()
    total_size = getFolderSize(folder_path)
    progress_bar = tqdm(
        total=total_size,
        unit="B",
        unit_scale=True,
        unit_divisor=1024,
        desc="Compressing",
    )

    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                file_path = os.path.join(root, file)
                tar.add(file_path, arcname=os.path.relpath(file_path, folder_path))
                progress_bar.update(os.path.getsize(file_path))

    progress_bar.close()
    buffer.seek(start_byte)
    while chunk := buffer.read(1024 * 1024):
        yield chunk
    print("Compressing complete, waiting for transfer.")


# starts the data stream to transfer data between the two computers
@app.get("/stream")
async def stream(range: str = Header(None)):
    global folderPath
    start_byte = 0

    if range:
        try:
            start_byte = int(range.replace("bytes=", "").split("-")[0])
        except ValueError:
            return {"error": "Invalid Range header"}

    return StreamingResponse(
        compress(folderPath, start_byte=start_byte),
        media_type="application/gzip",
        headers={"Content-Disposition": f"attachment; filename={OUTPUT_ARCHIVE}"},
    )


# check if the other computer is running this program
@app.get("/areyouthere")
async def areYouThere():
    if folderPath != "":
        if os.path.isdir(folderPath):
            return {"path": folderPath, "port": serverPort, "ready": isReadyForTransfer}
    return {"error": "Folder path unset or incorrect"}


# let the computer know that the content has started being downloaded
@app.get("/startReceiving/{ip}")
async def startReceiving(ip: str):
    asyncio.create_task(receiveFolder(ip))
    return {"started": True}


# let the computer know when they have finished downloading and setting everything up
@app.get("/finishedReceiving")
async def finishedReceiving():
    global isDone
    isDone = True
    return


# sends the clips.json library list file
@app.get("/libraryList")
async def getLibraryList():
    return FileResponse(
        path=os.path.join(os.getenv("APPDATA"), "Medal", "store", "clips.json"),
        media_type="application/json",
        filename="clips.json",
    )


# runs the server
def runServer():
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=serverPort,
    )


# prompts user some basic questions to ensure functionality even if they have edited the medal settings before or if they have local port conflicts
# also allows user to select from all the valid pcs on their network to send the data to
async def main():
    global folderPath
    global serverPort
    global isReadyForTransfer

    loop = True
    while loop:
        port = input(
            "Before we begin, what port would you like to use for sending your data? The default is 6789 \nIf you do not know what this means, please skip the question. \nPress enter to skip this question and use the default port "
        )
        try:
            if port == "" or port == " " or port == None:
                loop = False
                serverPort = 6789
            else:
                port = int(port)
                serverPort = port
                loop = False
        except:
            port = 6789
            print("\n\nThat does not seem to be a valid port.")

    input("\n\nClick enter to start the webserver that powers this script")
    threading.Thread(target=runServer, daemon=True).start()

    time.sleep(0.5)

    os.system("cls")

    print("Welcome! To get this running I'm going to ask you few questions.\n")

    loop = True
    while loop:
        isReceiving = input(
            "\n(Y/N) is this the computer that will be RECEIVING the Medal transfer? "
        )
        if isReceiving.lower() == "n" or isReceiving.lower() == "y":
            loop = False
        else:
            print("I'm not sure what you mean by that, please only answer Y/N")

    loop = True
    while loop:
        folder = input(
            "\nWhat is your Medal folder? Click only enter if you have never changed it from the default.\n"
        )
        if folder == "" or folder == " " or folder == None:
            if os.path.isdir("C:/Medal"):
                if isReceiving.lower() == "y":
                    folderPath = "C:/Medal"
                    isReadyForTransfer = True
                    print(
                        "\n\nAwaiting file transfer, this window will update when one is received"
                    )
                    while True:
                        time.sleep(60)

                size = getFolderSize("C:/Medal")
                if size != 0:
                    input(
                        f"\n\nYou are going to be transfering a compressed ~{ round(size / (2**30), 3) }GB worth of data over your local network. This will take up space on the remote drive receiving the transfer, please make sure you have enough storage. \n\nClick enter to continue, click ctrl+c to back out."
                    )
                    folderPath = "C:/Medal"
                    loop = False
                else:
                    print(
                        "You don't seem to be using the default Medal folder. Please double check that you didn't manually change your clipping location."
                    )
            else:
                print(
                    "You don't seem to be using the default Medal folder. Please double check that you didn't manually change your clipping location."
                )
        else:
            if os.path.isdir(folder):
                if isReceiving.lower() == "y":
                    folderPath = "C:/Medal"
                    isReadyForTransfer = True
                    print(
                        "\n\nAwaiting file transfer, this window will update when one is received"
                    )
                    while True:
                        time.sleep(60)
                size = getFolderSize(folder)
                if size != 0:
                    input(
                        f"\n\nYou are going to be recieving a compressed ~{ round(size / (2**30), 3) }GB worth of data over your local network. This will take up space on the remote drive receiving the transfer, please make sure you have enough storage. \n\nClick enter to continue, click ctrl+c to back out."
                    )

                    folderPath = folder
                    loop = False
                else:
                    print(
                        "\n\nThat folder doesn't appear to be valid. Please give me the exact folder path to your Medal clipping directory. You can find this in the Medal recording settings."
                    )
            else:
                print(
                    "You don't seem to be using the default Medal folder. Please double check that you didn't manually change your clipping location."
                )
    os.system("cls")

    input(
        "Awesome. I'm going to start looking for some devices on your network running Medal. Please make sure any devices are on and connected to the same wifi. \nClick enter to start the scan"
    )
    ips, localIP = getIps()
    num = "temp"
    loop = True
    while loop:
        while type(num) != int:
            try:
                num = input(
                    "Enter the numerical position of the device you want to send your Medal backup to. (type exit to exit)\n"
                )
                if num.lower() == "exit":
                    exit()
                else:
                    num = int(num)

            except:
                num = "error"
        try:
            if num > len(ips) or num - 1 < 0:
                print("That computer doesn't exist in the list!")
                num = "temp"
            elif ips[int(num) - 1] == localIP:
                print("You cannot send files to yourself!")
                num = "temp"
            else:
                data = json.loads(
                    requests.get(
                        f"http://{ips[int(num) - 1]}:{serverPort}/areyouthere"
                    ).text
                )
                data["path"]
                if data["ready"] == True:
                    loop = False
                else:
                    print(
                        "The other computer is not set up yet. Please procede through the steps until you reach the question about receiving a file transfer. Please answer yes to that question."
                    )
        except Exception as e:
            print(e)
            print(
                "\nThe receiving computer does not seem to have the program set up. Please make sure you have set up this same program on your other computer. Please also make sure you are running the exact same port on both machines. To change the port you'll need to restart this program."
            )
            num = "temp"
    input(
        "\n\nPlease make sure not to close the script or shut off your wifi while the script is running or you may experience data loss.\n\nClick enter to start the transfer"
    )

    os.system("cls")

    if json.loads(
        requests.get(
            f"http://{ips[int(num) - 1]}:{serverPort}/startReceiving/{localIP}"
        ).text
    )["started"]:
        print(
            "\nConnection formed, your file transfer has started.\nPlease make sure not to close the script or shut off your wifi while the script is running or you may experience data loss."
        )
    while not isDone:
        time.sleep(5)
    print("The transfer is all done! You can safely close this window now :)")
    input("Press enter to end the program")
    exit()


# run everything
asyncio.run(main())
