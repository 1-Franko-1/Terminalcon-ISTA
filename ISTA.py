import asyncio
import subprocess
import sys
from ollama import chat
from prompt_toolkit.shortcuts import PromptSession
from prompt_toolkit.styles import Style as PromptStyle
from web import *
import re
import threading
import keyboard  # Windows/Linux only, not Mac without sudo

# Remove colorama imports and init
session = PromptSession()

is_generating = False
abort_generation = False
do_tool_auth = True
model = "huihui_ai/qwen3-abliterated:8b-v2-q4_K_M"

# Define Windows CMD color codes
class Colors:
    PROMPT = "\033[94m"    # Blue
    INFO = "\033[92m"      # Green
    WARNING = "\033[93m"   # Yellow
    ERROR = "\033[91m"     # Red
    STREAM_LABEL = "\033[2m"  # Dim
    RESET = "\033[0m"      # Reset

# Enable Windows Console Virtual Terminal Sequences
def enable_virtual_terminal():
    import ctypes
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
    mode = ctypes.c_ulong()
    kernel32.GetConsoleMode(handle, ctypes.byref(mode))
    mode.value |= 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    kernel32.SetConsoleMode(handle, mode)

def listen_for_abort():
    global abort_generation
    while True:
        keyboard.wait('ctrl+w')
        if is_generating:
            abort_generation = True
        else:
            print(f"\n{Colors.ERROR}No AI generation active.{Colors.RESET}")
            print(f"{Colors.PROMPT}>>> {Colors.RESET}", end="", flush=True)

enable_virtual_terminal()

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
                    "content": {"type": "string", "description": "The content to write into the file."}
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
                    "query": {"type": "string", "description": "The search query."},
                    "num_results": {"type": "integer", "description": "Number of results to return.", "default": 5}
                },
                "required": ["query"],
                "additionalProperties": False
            },
            "strict": True
        }
    }
]

SYS_MSG = """
You are ISTA, short for Integrated Smart Terminal Assistant, a smart terminal assistant designed to help users with various tasks, including executing commands, providing information, and assisting with programming tasks. 
You can execute shell commands and provide responses in a conversational manner.
You can also search the web for information and provide relevant results to the user.
You are a agentic AI. Until you send a message without a tool call, you can execute tools one after another.
"""

async def llm_stream(messages, tools=None):
    """
    Streams LLM responses and collects any tool calls.
    Yields (current_response, tool_calls).
    """
    stream = chat(model=model, messages=messages, tools=tools, stream=True)
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

async def display_stream(stream_gen):
    global is_generating, abort_generation
    is_generating = True
    partial = ""
    in_think = False
    calls = []

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
                    print(f"{Colors.STREAM_LABEL}\n\033[1mThinking...\033[22m{Colors.RESET} ", end="", flush=True)
                    output = after
                    in_think = True

                elif in_think and '</think>' in output:
                    reason, _, after = output.partition('</think>')
                    print(f"{Colors.STREAM_LABEL}{reason}{Colors.RESET}", end="", flush=True)
                    print(f"{Colors.STREAM_LABEL}\033[1mFinished thinking...\033[22m{Colors.RESET}")
                    print("\033[F", end="")
                    output = after
                    in_think = False

                else:
                    color = Colors.STREAM_LABEL if in_think else Colors.RESET
                    print(f"{color}{output}{Colors.RESET}", end="", flush=True)
                    break
    finally:
        is_generating = False
        abort_generation = False

    print()

    # Clean up think tags
    partial = re.sub(r'<think>.*?</think>', '', partial.strip(), flags=re.DOTALL).strip()
    return partial, calls

async def main():
    global model
    print(f"{Colors.INFO}Welcome to the Integrated Smart Terminal Assistant (ISTA)!{Colors.RESET}")
    history = [{"role": "system", "content": SYS_MSG}]
    while True:
        user_input = await session.prompt_async(
            [('class:prompt', '>>> ')],
            style=PromptStyle.from_dict({
                'prompt': 'bold ansiblue',
                '': 'ansiwhite',
            }),
            placeholder='Send a message (? for help)'
        )

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
            continue
        
        if user_input.strip() in ["tools", "t"]:
            global tools
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
                    history = json.load(f)
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
            history = []
            continue

        history += [{"role": "user", "content": user_input}]

        # Start streaming
        tool_calls = ["..."]
        while tool_calls:
            tool_calls = []
            partial, tool_calls = await display_stream(llm_stream(history, tools))

            # Handle any tool calls
            if tool_calls:
                history.append({"role": "assistant", "content": partial})
                for call in tool_calls:
                    name = call.function['name']
                    args = call.function['arguments']
                    if name == 'shell':
                        cmd = args['command']
                        inpt = args.get("input", "")
                        print("\033[F", end="")
                        if do_tool_auth:
                            choice = input(f"{Colors.WARNING}Run command '{cmd}'? (y/n): {Colors.RESET}")
                        else:
                            choice = 'y'

                        if choice.strip().lower() == 'y':
                            print(f"{Colors.INFO}Executing: {cmd}{Colors.RESET}")
                            result = subprocess.run(cmd, text=True, shell=True,
                                                    capture_output=True, input=inpt, encoding="utf-8", errors="replace")
                            output = (result.stdout or result.stderr).strip()
                            history.append({
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
                                history.append({
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
                        history.append({
                            "role": "tool",
                            "name": name,
                            "content": json.dumps({"result": "Searched web.", "query": content, "num_results": num_sites, "result": web_search_result})
                        })
        
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

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{Colors.INFO}Goodbye!{Colors.RESET}")