import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const launch = JSON.parse(process.argv[2]);
const probeCall = process.argv[3] ? JSON.parse(process.argv[3]) : null;
const client = new Client({ name: "bb-l5-doctor", version: "1.0.0" });
const transport = new StdioClientTransport({
  command: launch.command,
  args: launch.args ?? [],
  env: process.env,
  stderr: "pipe",
});

try {
  await client.connect(transport);
  const response = await client.listTools();
  const result = {
    connected: true,
    tool_count: response.tools.length,
    tools: response.tools.map((tool) => tool.name),
  };
  if (probeCall) {
    result.call = await client.callTool(probeCall);
  }
  process.stdout.write(JSON.stringify(result));
  await client.close();
} catch (error) {
  process.stdout.write(JSON.stringify({
    connected: false,
    error: error instanceof Error ? error.message : String(error),
  }));
  try {
    await client.close();
  } catch {
    // The transport may already be closed after a failed handshake.
  }
  process.exitCode = 1;
}
