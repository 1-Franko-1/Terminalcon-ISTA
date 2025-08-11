import asyncio
import subprocess
import sys
from ollama import chat
from web import *
import re
import threading
import keyboard
import getpass
import platform
import copy
import whisper
import shlex
import queue

whisper_model = whisper.load_model("small")

username = getpass.getuser()

is_generating = False
abort_generation = False
do_tool_auth = True
num_agents = 0
model = "huihui_ai/qwen3-abliterated:8b-v2-q4_K_M"
image_model = "gemma3:4b-it-qat"

# Colors :3
class Colors:
    PROMPT = "\033[94m"    # Blue
    INFO = "\033[92m"      # Green
    WARNING = "\033[93m"   # Yellow
    ERROR = "\033[91m"     # Red
    STREAM_LABEL = "\033[2m"  # Dim
    RESET = "\033[0m"      # Reset

# Enable Windows Console Virtual Terminal Sequences
def enable_virtual_terminal():
    if platform.system() == 'Windows':
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        mode.value |= 0x0004
        kernel32.SetConsoleMode(handle, mode)
    pass

enable_virtual_terminal()

def listen_for_abort():
    global abort_generation
    while True:
        keyboard.wait('ctrl+w')
        if is_generating:
            abort_generation = True
        else:
            print(f"\n{Colors.ERROR}No AI generation active.{Colors.RESET}")
            print(f"{Colors.PROMPT}>>> {Colors.RESET}", end="", flush=True)

# Tool definitions
tools = [
    {
        "type": "function",
        "function": {
            "name": "shell",
            "description": "Executes a windows cmd command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The command to execute."},
                    "input": {"type": "string", "description": "Commands input, not required. Only use when executing a command that requires a user input."}
                },
                "required": ["command"],
                "additionalProperties": False
            },
            "strict": True
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Lets you put any content into a file. Use this instead of shell commands to edit files. This is safer and more reliable. Also if the file doesnt exist, this will create it. BUT this cant create directories, so you have to make sure the directory exists.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "The name of the file to edit. Can be a full path."},
                    "content": {"type": "string", "description": "The content to write into the file. You cannot put special characters in here."}
                },
                "required": ["filename", "content"],
                "additionalProperties": False
            },
            "strict": True
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web",
            "description": "Searches the web using Google.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query. Can be a link if you want that specific link scraped."},
                    "num_results": {"type": "integer", "description": "Number of results to return. When scraping a specific link, this doesnt matter.", "default": 3}
                },
                "required": ["query", "num_results"],
                "additionalProperties": False
            },
            "strict": True
        }
    }
]

SYS_MSG = f"""
You are ISTA, short for Integrated Smart Terminal Assistant, a smart terminal assistant designed to help users with various tasks, including executing commands, providing information, and assisting with programming tasks. 
You can execute shell commands and provide responses in a conversational manner.
You can also search the web for information and provide relevant results to the user.
You are a agentic AI. Until you send a message without a tool call, you can execute tools one after another.
You may execute a tool any time in your response, so, yes you can execute a tool after generating text.
You are chatting with a user named "{username}" (system name, might not be accurate).
You can see images, text, and other files.
"""

SECOND_SYS_MSG = f"""
You are a AI chatting on the behalf of "{username}" (system name, might not be accurate).
You are chatting to ISTA, a smart terminal assistant designed to help users with various tasks, including executing commands, providing information, and assisting with programming tasks. 
"""

AGENT_SYS_MSG = f"""
You are an agent, meant to execute tasks for another ai.
Once you compleated a task, generate a response that includes the task result, and a description of what you did to get the task result.
"""

def describe_image(image_path: str) -> str:
    res = chat(
        model=image_model,
        messages=[
            {
                'role': 'user',
                'content': 'Describe this image in detail:',
                'images': [image_path]
            }
        ],
        stream=True
    )
    
    description = ""
    for chunk in res:
        description += chunk['message']['content']
    
    return description

async def llm_stream(messages, tools=None):
    """
    Streams LLM responses and collects any tool calls.
    Yields (current_response, tool_calls).
    """
    stream = chat(
        model=model, 
        messages=messages, 
        tools=tools,
        stream=True,
        options = {
            "num_keep": 4096,
            "temperature": 0.6,
            "top_p": 0.95,
            "presence_penalty": 0.1,
            "frequency_penalty": 0.3,
            "penalize_newline": False,
            "f16_kv": True
        }
    )
    aggregated = ""
    calls = []

    for chunk in stream:
        msg = chunk.get('message', {})
        content = msg.get('content', '')
        new_calls = msg.get('tool_calls', [])

        if content:
            aggregated += content
            yield aggregated, calls
        if new_calls:
            calls.extend(new_calls)

async def read_stream(stream_gen):
    response = ""
    reasoning = ""
    in_think = False

    async for resp, calls in stream_gen:
        # Detect and strip <think> blocks
        new_text = resp[len(response):]
        response = resp

        while new_text:
            if not in_think and '<think>' in new_text:
                before, _, after = new_text.partition('<think>')
                new_text = after
                in_think = True

            elif in_think and '</think>' in new_text:
                reason, _, after = new_text.partition('</think>')
                reasoning += reason
                new_text = after
                in_think = False

            else:
                if in_think:
                    reasoning += new_text
                break

    response = re.sub(r'<think>.*?</think>', '', response.strip(), flags=re.DOTALL).strip()

    return response, reasoning, calls

async def display_stream(stream_gen):
    global is_generating, abort_generation
    is_generating = True
    partial = ""
    reasoning = ""
    in_think = False
    calls = []
    reasoning_tokens = 0
    response_tokens = 0

    try:
        async for resp, calls in stream_gen:
            if abort_generation:
                print(f"\n{Colors.ERROR}Generation aborted by user.{Colors.RESET}")
                break

            new_text = resp[len(partial):]
            partial = resp

            output = new_text
            while output:
                if not in_think and '<think>' in output:
                    before, _, after = output.partition('<think>')
                    print(before, end="", flush=True)
                    response_tokens += len(before.split())
                    print(f"{Colors.STREAM_LABEL}\n\033[1mThinking...\033[22m{Colors.RESET} ", end="", flush=True)
                    output = after
                    in_think = True

                elif in_think and '</think>' in output:
                    reason, _, after = output.partition('</think>')
                    print(f"{Colors.STREAM_LABEL}{reason}{Colors.RESET}", end="", flush=True)
                    print(f"{Colors.STREAM_LABEL}\033[1mFinished thinking...\033[22m{Colors.RESET}")
                    print("\033[F", end="")
                    reasoning += reason
                    reasoning_tokens += len(reason.split())
                    output = after
                    in_think = False

                else:
                    color = Colors.STREAM_LABEL if in_think else Colors.RESET
                    print(f"{color}{output}{Colors.RESET}", end="", flush=True)
                    if in_think:
                        reasoning += output
                        reasoning_tokens += len(output.split())
                    else:
                        response_tokens += len(output.split())
                    break
    finally:
        is_generating = False
        abort_generation = False

    print()

    # Clean up think tags
    partial = re.sub(r'<think>.*?</think>', '', partial.strip(), flags=re.DOTALL).strip()
    
    # Replace the token counting print with our new counts
    print(f"{Colors.STREAM_LABEL}{reasoning_tokens}{Colors.RESET} ", end="")
    print(f"{Colors.INFO}|{Colors.RESET} {response_tokens}")

    return partial, calls, reasoning

async def process_tool_calls(calls, messages):
    if calls:
        for call in calls:
            name = call.function['name']
            args = call.function['arguments']
            if name == 'shell':
                cmd = args['command']
                inpt = args.get("input", "")

                if do_tool_auth:
                    choice = input(f"{Colors.WARNING}Run command '{cmd}'? (y/n): {Colors.RESET}")
                else:
                    choice = 'y'

                if choice.strip().lower() == 'y':
                    print(f"{Colors.INFO}Executing: {cmd}{Colors.RESET}")
                    if platform.system() == 'Windows':
                        # Windows-style command execution
                        result = subprocess.run(cmd, text=True, shell=True,
                                            capture_output=True, input=inpt, encoding="utf-8", errors="replace", timeout=60)
                    else:
                        # Unix-style command execution
                        cmd_args = shlex.split(cmd)
                        result = subprocess.run(cmd_args, text=True,
                                            capture_output=True, input=inpt, encoding="utf-8", errors="replace", timeout=60)
                    output = (result.stdout or result.stderr).strip()
                    messages.append({
                        'role': 'tool',
                        'name': name,
                        'content': f"Executed '{cmd}', output:\n{output}"
                    })
                else:
                    print(f"{Colors.ERROR}Command canceled.{Colors.RESET}")

            if name == 'edit_file':
                filename = args['filename']
                content = args['content']
                print("\033[F", end="")
                if do_tool_auth:
                    choice = input(f"{Colors.WARNING}Write to file '{filename}'? (y/n): {Colors.RESET}")
                else:
                    choice = 'y'

                if choice.strip().lower() == 'y':
                    try:
                        with open(filename, 'w') as f:
                            f.write(content)
                        print(f"{Colors.INFO}File '{filename}' edited successfully.{Colors.RESET}")
                        messages.append({
                            "role": "tool",
                            "name": name,
                            "content": json.dumps({"result": "Edited file.", "filename": filename, "content": content})
                        })
                    except Exception as e:
                        print(f"{Colors.ERROR}Error writing to file: {e}{Colors.RESET}")

            if name == "web":
                content = args["query"]
                num_sites = args["num_results"]
                print(f"{Colors.INFO}Searching the web for '{content}'...{Colors.RESET}")
                web_search_result = await web_search(content, num_sites)
                messages.append({
                    "role": "tool",
                    "name": name,
                    "content": json.dumps({"result": "Searched web.", "query": content, "num_results": num_sites, "result": web_search_result})
                })

            if name == "deploy_agent":
                agents = args["agents"]
                agents = agents.replace("\\", "\\\\")
                print(f"{Colors.INFO}Deploying agent '{agents}'...{Colors.RESET}")
                agents = json.loads(agents)
                agents_done = 0
                while agents_done != len(agents):
                    for agentnum in agents:
                        agentprompt = agents[agentnum]
                        q = queue.Queue()
                        threading.Thread(target=deploy_agent, args=(agentprompt, q), daemon=True).start()
                        result = q.get()

                        print(f"{Colors.INFO}Agent {agentnum} returned: {result}{Colors.RESET}")
                        
                        messages.append({
                            "role": "tool",
                            "name": name,
                            "content": json.dumps({"result": "Agent returned result.", "agent number": agentnum, "result": result})
                        })
                        agents_done += 1
    
    return messages

async def agent(task_str):
    global model, tools
    messages = [
        {'role': 'system', 'content': AGENT_SYS_MSG},
        {'role': 'user', 'content': task_str}
    ]

    resp, _, calls = await read_stream(llm_stream(messages, tools))

    # now, process tool calls
    if calls:
        messages.append({"role": "assistant", "content": resp})
        messages = await process_tool_calls(calls, messages)

        resp, _, _ = await read_stream(llm_stream(messages, None))

    return resp

def deploy_agent(task_str, out_q):
    response = asyncio.run(agent(task_str))
    out_q.put(response)

async def main():
    global model, tools
    local_tools = tools.copy()
    if num_agents > 0:
        local_tools += [
            {
                "type": "function",
                "function": {
                    "name": "deploy_agent",
                    "description": "Need to do stuff in parralel? Agents got you! Just make a prompt and you can deploy an agent that will do that task autonomusly!",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "agents": {"type": "string", "description": "A json of all agents, eg. {'1': 'prompt1', '2': 'prompt2'}. The number is the agent number, required to keep track of the agents. You can deploy up to "+str(num_agents)+" agents. An agent can only do one task per agent."}
                        },
                        "required": ["agents"],
                        "additionalProperties": False
                    },
                    "strict": True
                }
            }
        ]

    print(f"{Colors.INFO}Welcome to the Integrated Smart Terminal Assistant (ISTA)!{Colors.RESET}")
    print(f"{Colors.INFO}Type '?' or 'help' for a list of available user commands.{Colors.RESET}")
    print(f"{Colors.INFO}Type '--file' to upload file(s) for the ai to see.{Colors.RESET}")
    print(f"{Colors.INFO}Type 'ai' to let an ai respond to the ai (autogenerates a prompt based on current converastion).{Colors.RESET}")
    history = [{"role": "system", "content": SYS_MSG}]
    while True:
        user_input = input(f"{Colors.PROMPT}>>> {Colors.RESET}")

        if user_input.strip().startswith('"""'):
            if user_input.strip().endswith('"""') and len(user_input.strip()) > 3:
                user_input = user_input.strip()[3:-3].strip()
            else:
                final_input = user_input.lstrip()[3:] + "\n"
                while True:
                    user_input = input(f"{Colors.PROMPT}... {Colors.RESET}")
                    if '"""' in user_input:
                        final_input += user_input.split('"""')[0]
                        break
                    final_input += user_input + "\n"
                user_input = final_input.strip()

        matches = re.findall(r'--file\s+"([^"]+)"', user_input)
        if matches:
            for file_path in matches:
                extension = file_path.split('.')[-1]
                print(f"{Colors.INFO}MCP has received file: {file_path}, extension: {extension}{Colors.RESET}")
                if extension in ('jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp'):
                    image_desc = describe_image(file_path)

                    if len(image_desc) > 2000:
                        image_desc = image_desc[:2000]+"..."
                        
                    history.append({
                        "role": "tool",
                        "name": "read_file",
                        "content": json.dumps({"content": f"User sent image, auto generated description: {image_desc}", "file_path": file_path})
                    })
                elif extension in ('mp3', 'wav', 'ogg', 'flac'):
                    result = whisper.transcribe(whisper_model, file_path)

                    if len(result['text']) > 2000:
                        result['text'] = result['text'][:2000]+"..."

                    history.append({
                        "role": "tool",
                        "name": "read_file",
                        "content": json.dumps({"content": f"User sent audio, auto generated transcript: {result['text']}", "file_path": file_path})
                    })
                else:
                    if os.path.exists(file_path):
                        with open(file_path, 'r', encoding='utf-8') as file:
                            file_content = file.read()

                        if len(file_content) > 2000:
                            file_content = file_content[:2000]+"..."

                        history.append({
                            "role": "tool",
                            "name": "read_file",
                            "content": json.dumps({"content": f"User sent file, content: {file_content}", "file_path": file_path})
                        })
                    else:
                        print(f"{Colors.ERROR}File not found: {file_path}{Colors.RESET}")

            # Remove all --file "..." occurrences from the user_input
            user_input = re.sub(r'--file\s+"[^"]+"', '', user_input).strip()

        if user_input == 'ai':
            copied_history = copy.deepcopy(history)
            for message in copied_history:
                if message['role'] == 'assistant':
                    message['role'] = 'user'
                elif message['role'] == 'user':
                    message['role'] = 'assistant'

            # replace the system message with the second system message
            copied_history[0]['content'] = SECOND_SYS_MSG

            # use display_stream to generate a response with this history
            user_input, _, _ = await display_stream(llm_stream(copied_history, tools))

        if not user_input:
            continue

        if user_input.lower() in ['exit', 'quit', 'q']:
            print(f"{Colors.INFO}Exiting...{Colors.RESET}")
            break

        if user_input.strip() in ["help", "?"]:
            print(f"{Colors.INFO} General commands:")
            print(f"{Colors.INFO} - help, ? : Show this help message")
            print(f"{Colors.INFO} - exit, quit, q : Exit the assistant")
            print(f"{Colors.INFO} AI Controll commands:")
            print(f"{Colors.INFO} - clear, c, cls : Clear the terminal screen and llms memory")
            print(f"{Colors.INFO} - model, m: Change the base model (default: {model})")
            print(f"{Colors.INFO} - tools, t : Toggle tool execution mode")
            print(f"{Colors.WARNING} WARNING: YOU CANNOT ENABLE TOOLS AFTER DISABLING THEM ONCE, YOU WILL HAVE TO RESTART THE SCRIPT!")
            print(f"{Colors.INFO} Additional commands:")
            print(f"{Colors.INFO} - export, exp : Export the current conversation history")
            print(f"{Colors.INFO} - import, imp : Import conversation history from a file")
            print(f"{Colors.INFO} Parameters:")
            print(f"{Colors.INFO} - --file 'path/to/file' : Send a file to the AI")
            continue
        
        if user_input.strip() in ["tools", "t"]:
            tools = None if tools else tools
            print(f"{Colors.WARNING}Tools {'disabled' if tools is None else 'enabled'}. AI will {'not ' if tools is None else ''}execute any tools.{Colors.RESET}")

        if user_input.strip() in ["export", "exp"]:
            export_history = [msg for msg in history if msg['role'] != 'system']
            filename = input(f"{Colors.INFO}Enter filename to export history (default: history.json): {Colors.RESET}")
            if not filename.strip():
                filename = "history.json"
            with open(filename, 'w') as f:
                json.dump(export_history, f, indent=4)
            print(f"{Colors.WARNING}History exported to {filename}{Colors.RESET}")
            continue

        if user_input.strip() in ["import", "imp"]:
            filename = input(f"{Colors.WARNING}Enter filename to import history from (default: history.json): {Colors.RESET}")
            if not filename.strip():
                filename = "history.json"
            try:
                with open(filename, 'r') as f:
                    history += json.load(f)
                print(f"{Colors.WARNING}History imported from {filename}{Colors.RESET}")
            except FileNotFoundError:
                print(f"{Colors.ERROR}File not found: {filename}{Colors.RESET}")
            except json.JSONDecodeError:
                print(f"{Colors.ERROR}Error decoding JSON from file: {filename}{Colors.RESET}")
            continue

        if user_input.strip() in ["model", "m"]:
            new_model = input(f"{Colors.INFO}Enter new model name (default: {model}): {Colors.RESET}")
            if not new_model.strip():
                new_model = model
            model = new_model
            print(f"{Colors.WARNING}Model changed to: {model}{Colors.RESET}")
            continue

        if user_input.strip() in ["clear", "c", "cls"]:
            history = [{"role": "system", "content": SYS_MSG}]
            continue

        history += [{"role": "user", "content": user_input}]

        # Start streaming
        tool_calls = ["i put one string here cuz i wanna lower the lines of code so i dont use a startup variable"]
        while tool_calls:
            partial, tool_calls, reasoning = await display_stream(llm_stream(history, local_tools))
            
            # Handle any tool calls
            if tool_calls:
                history.append({"role": "assistant", "content": partial})
                history = await process_tool_calls(tool_calls, history)
        
        history.append({"role": "assistant", "content": partial})

if __name__ == '__main__':
    # Start abort listener thread
    threading.Thread(target=listen_for_abort, daemon=True).start()

    if '--model' in subprocess.list2cmdline(sys.argv):
        model_index = sys.argv.index('--model') + 1
        if model_index < len(sys.argv):
            model = sys.argv[model_index]
            print(f"{Colors.WARNING}Using model: {model}{Colors.RESET}")

    if '--no-tools' in subprocess.list2cmdline(sys.argv):
        tools = None
        print(f"{Colors.WARNING}Tools disabled. AI will not execute any tools.{Colors.RESET}")

    if '--disable-auth' in subprocess.list2cmdline(sys.argv):
        print(f"{Colors.WARNING}Authentication disabled. The AI can now execute tools without authentication.{Colors.RESET}")
        do_tool_auth = False

    if '--agents' in sys.argv:
        print(f"{Colors.WARNING}WARNING: THIS FEATURE IS HIGHLY EXPERIMENTAL! USE AT YOUR OWN RISK!!!{Colors.RESET}")
        agents_index = sys.argv.index('--agents') + 1
        num_agents = int(sys.argv[agents_index])
        print(f"{Colors.WARNING}Allowing ai to deploy {num_agents} agents.{Colors.RESET}")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{Colors.INFO}Goodbye!{Colors.RESET}")