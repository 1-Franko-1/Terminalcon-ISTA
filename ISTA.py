import asyncio
import subprocess
import sys
from ollama import chat
from prompt_toolkit.shortcuts import PromptSession
from prompt_toolkit.styles import Style as PromptStyle
from web import *

# Remove colorama imports and init
session = PromptSession()

agent_mode = False
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
                    "command": {"type": "string", "description": "The command to execute."}
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
    partial = ""
    in_think = False
    calls = []

    async for resp, calls in stream_gen:
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

    print()
    return partial.strip(), calls

async def main():
    global model
    print(f"{Colors.INFO}Welcome to the Integrated Smart Terminal Assistant (ISTA)! Type 'help' for commands.{Colors.RESET}")
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
            print(f"{Colors.INFO} - agent, a : Toggle agent mode")
            print(f"{Colors.INFO} - model, m: Change the base model (default: {model})")
            print(f"{Colors.INFO} - tools, t : Toggle tool execution mode")
            print(f"{Colors.INFO} WARNING: YOU CANNOT ENABLE TOOLS AFTER DISABLING THEM ONCE, YOU WILL HAVE TO RESTART THE SCRIPT!")
            print(f"{Colors.INFO} Additional commands:")
            print(f"{Colors.INFO} - export, exp : Export the current conversation history")
            print(f"{Colors.INFO} - import, imp : Import conversation history from a file")
            continue
        
        if user_input.strip() in ["agent", "a"]:
            global agent_mode
            agent_mode = not agent_mode
            mode = True if agent_mode else False
            agent_mode = mode

            print(f"{Colors.INFO}Agent mode {mode}. AI can now execute tools autonomously.{Colors.RESET}")

            if agent_mode:
                history[0]['content'] = SYS_MSG + "\nYou are now in agent mode. Untill you send a message without a tool call, you can execute tools one after another."
            else:
                history[0]['content'] = SYS_MSG

            continue

        if user_input.strip() in ["tools", "t"]:
            global tools
            tools = None if tools else tools
            print(f"{Colors.INFO}Tools {'disabled' if tools is None else 'enabled'}. AI will {'not ' if tools is None else ''}execute any tools.{Colors.RESET}")

        if user_input.strip() in ["export", "exp"]:
            filename = input(f"{Colors.INFO}Enter filename to export history (default: history.json): {Colors.RESET}")
            if not filename.strip():
                filename = "history.json"
            with open(filename, 'w') as f:
                json.dump(history, f, indent=4)
            print(f"{Colors.INFO}History exported to {filename}{Colors.RESET}")
            continue

        if user_input.strip() in ["import", "imp"]:
            filename = input(f"{Colors.INFO}Enter filename to import history from (default: history.json): {Colors.RESET}")
            if not filename.strip():
                filename = "history.json"
            try:
                with open(filename, 'r') as f:
                    history = json.load(f)
                print(f"{Colors.INFO}History imported from {filename}{Colors.RESET}")
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
            print(f"{Colors.INFO}Model changed to: {model}{Colors.RESET}")
            continue

        if user_input.strip() in ["clear", "c", "cls"]:
            history = []
            continue

        history += [{"role": "user", "content": user_input}]

        # Start streaming
        tool_calls = []
        first_run = True
        while (tool_calls and agent_mode) or first_run:
            first_run = False
            partial, tool_calls = await display_stream(llm_stream(history, tools))

            # Handle any tool calls
            if tool_calls:
                history.append({"role": "assistant", "content": partial})
                for call in tool_calls:
                    name = call.function['name']
                    args = call.function['arguments']
                    if name == 'shell':
                        cmd = args['command']
                        print("\033[F", end="")
                        if do_tool_auth:
                            choice = input(f"{Colors.WARNING}Run command '{cmd}'? (y/n): {Colors.RESET}")
                        else:
                            choice = 'y'

                        if choice.strip().lower() == 'y':
                            print(f"{Colors.INFO}Executing: {cmd}{Colors.RESET}")
                            result = subprocess.run(cmd, text=True, shell=True,
                                                    capture_output=True, encoding="utf-8", errors="replace")
                            output = (result.stdout or result.stderr).strip()
                            history.append({
                                'role': 'tool',
                                'name': name,
                                'content': f"Executed '{cmd}', output:\n{output}"
                            })
                        else:
                            print(f"{Colors.ERROR}Command canceled.{Colors.RESET}")

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
        
        if not agent_mode and tool_calls:
            # generate response without tool calls
            partial, tool_calls = await display_stream(llm_stream(history, None))
        
        history.append({"role": "assistant", "content": partial})

if __name__ == '__main__':
    enable_virtual_terminal()

    if '--agent' in subprocess.list2cmdline(sys.argv):
        agent_mode = True
        print(f"{Colors.INFO}Agent mode enabled. AI can now execute tools autonomously.{Colors.RESET}")

    if '--model' in subprocess.list2cmdline(sys.argv):
        model_index = sys.argv.index('--model') + 1
        if model_index < len(sys.argv):
            model = sys.argv[model_index]
            print(f"{Colors.INFO}Using model: {model}{Colors.RESET}")

    if '--no-tools' in subprocess.list2cmdline(sys.argv):
        tools = None
        print(f"{Colors.INFO}Tools disabled. AI will not execute any tools.{Colors.RESET}")

    if '--disable-auth' in subprocess.list2cmdline(sys.argv):
        print(f"{Colors.INFO}Authentication disabled. The ai can now execute tools without authentication.{Colors.RESET}")
        do_tool_auth = False

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{Colors.INFO}Goodbye!{Colors.RESET}")