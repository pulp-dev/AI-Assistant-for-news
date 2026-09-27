import express from 'express';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { createBitrixClient } from './lib/bitrix.js';
import { registerDealTools } from './tools/deals.js';
import { registerCompanyTools } from './tools/companies.js';
import { registerContactTools } from './tools/contacts.js';
import { registerDiskTools } from './tools/disk.js';

const BITRIX_BASE = process.env.BITRIX_BASE;
const MCP_TOKEN = process.env.MCP_TOKEN;
const PORT = Number(process.env.PORT || 3000);
if (!BITRIX_BASE) throw new Error('BITRIX_BASE is not set');
if (!MCP_TOKEN) throw new Error('MCP_TOKEN is not set');

const bitrix = createBitrixClient(BITRIX_BASE);
const app = express();
app.use(express.json({ limit: '2mb' }));

function createServer() {
  const server = new McpServer({ name: 'INDIV Bitrix24', version: '1.0.0' });
  registerDealTools(server, bitrix);
  registerCompanyTools(server, bitrix);
  registerContactTools(server, bitrix);
  registerDiskTools(server, bitrix);
  return server;
}

app.get('/', (_req, res) => res.status(200).send('INDIV Bitrix24 MCP is running'));
app.post(`/mcp/${MCP_TOKEN}`, async (req, res) => {
  const server = createServer();
  const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined, enableJsonResponse: true });
  res.on('close', () => { transport.close().catch(() => {}); server.close().catch(() => {}); });
  try {
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
  } catch (err) {
    console.error(err);
    if (!res.headersSent) res.status(500).json({ error: 'MCP request failed' });
  }
});
app.get(`/mcp/${MCP_TOKEN}`, (_req, res) => res.status(405).send('Use POST'));
app.delete(`/mcp/${MCP_TOKEN}`, (_req, res) => res.status(405).send('Stateless MCP endpoint'));
app.listen(PORT, '0.0.0.0', () => console.log(`INDIV Bitrix24 MCP listening on ${PORT}`));
