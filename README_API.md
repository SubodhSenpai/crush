# Crush Command API

A FastAPI server that provides an HTTP interface to execute `crush.exe` commands via PowerShell.

## Features

- Execute crush.exe commands through a REST API
- PowerShell command execution with proper escaping
- Health check endpoint to verify crush.exe availability
- Comprehensive error handling and logging
- Async command execution with execution time tracking
- Support for all crush.exe command-line flags

## Installation

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

2. Ensure `crush.exe` is available in the current directory or in your PATH

## Running the Server

```bash
python main.py
```

The server will start on `http://localhost:9000`

## API Endpoints

### Health Check
```
GET /health
```
Returns the health status and crush.exe path information.

### Execute Crush Command
```
POST /execute
```

Execute a crush command with the following JSON payload:

```json
{
  "prompt": "Your prompt here",
  "model": "openai:gpt-4o",
  "cwd": "C:\\path\\to\\working\\directory",
  "yolo": true,
  "debug": false,
  "quiet": false
}
```

**Parameters:**
- `prompt` (required): The prompt to send to crush
- `model` (optional): Model to use in format "provider:model" (default: "openai:gpt-4o")
- `cwd` (optional): Current working directory
- `yolo` (optional): Automatically accept all permissions (default: true)
- `debug` (optional): Enable debug mode (default: false)
- `quiet` (optional): Hide spinner when using --prompt (default: false)

### Execute Raw PowerShell Command
```
POST /execute-raw?command=<powershell_command>
```

Execute a raw PowerShell command for testing purposes.

## Example Usage

### Using curl

```bash
# Health check
curl http://localhost:9000/health

# Execute crush command
curl -X POST "http://localhost:9000/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Hi can you please tell me what is 2+2 and also create me a calculator app and save the app in local please.",
    "model": "openai:gpt-4o",
    "cwd": "C:\\Users\\Subhodh\\Downloads\\proxieAIWorkflow\\proxieCore\\user-cc20df1c-81c5-42eb-bd1d-0e5872ec3173",
    "yolo": true,
    "debug": false
  }'
```

### Using Python

```python
import requests

# Execute the exact command from your example
command_data = {
    "prompt": "Hi can you please tell me what is 2+2 and also create me a calculator app and save the app in local please.",
    "model": "openai:gpt-4o",
    "cwd": r"C:\Users\Subhodh\Downloads\proxieAIWorkflow\proxieCore\user-cc20df1c-81c5-42eb-bd1d-0e5872ec3173",
    "yolo": True,
    "debug": False
}

response = requests.post("http://localhost:9000/execute", json=command_data)
result = response.json()

print(f"Success: {result['success']}")
print(f"Output: {result['output']}")
```

### Run the example script

```bash
python example_usage.py
```

## Response Format

```json
{
  "success": true,
  "command": ".\\crush.exe -p \"Your prompt\" -m openai:gpt-4o --cwd \"C:\\path\\to\\project\" -y -d",
  "message": "Command started in separate terminal (PID: 12345)",
  "process_id": 12345
}
```

## Error Handling

The API provides comprehensive error handling:

- **500 Internal Server Error**: When crush.exe is not found
- **500 Internal Server Error**: When command execution fails
- **422 Unprocessable Entity**: When request validation fails

## Logging

The server logs all command executions and errors. Check the console output for detailed information about command execution.

## API Documentation

Once the server is running, visit `http://localhost:9000/docs` for interactive API documentation powered by Swagger UI.

## Security Considerations

- The API runs with full system access via PowerShell
- Use appropriate authentication/authorization in production
- Be cautious with the `yolo` flag as it automatically accepts all permissions
- Consider running in a restricted environment for production use

## Troubleshooting

1. **crush.exe not found**: Ensure crush.exe is in the current directory or in your system PATH
2. **Permission errors**: Make sure the server has permission to execute PowerShell commands
3. **Command failures**: Check the error field in the response for detailed error information
4. **Connection refused**: Ensure the server is running on the correct port (8000)


uvicorn main:app --host 0.0.0.0 --port 9000 --reload 