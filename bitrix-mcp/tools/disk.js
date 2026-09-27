import { z } from 'zod';
import { textResult } from '../lib/bitrix.js';

export function registerDiskTools(server, bitrix) {
  server.registerTool('list_disk_storages', {
    description: 'List Bitrix24 Disk storages visible to the webhook user.', inputSchema: z.object({})
  }, async () => textResult((await bitrix('disk.storage.getlist', {})).result));

  server.registerTool('list_disk_storage_children', {
    description: 'List files/folders in a Bitrix24 Disk storage root.',
    inputSchema: z.object({ storageId: z.number().int().positive() })
  }, async ({ storageId }) => textResult((await bitrix('disk.storage.getchildren', { id: storageId })).result));

  server.registerTool('list_disk_folder_children', {
    description: 'List files/folders inside a Bitrix24 Disk folder.',
    inputSchema: z.object({ folderId: z.number().int().positive() })
  }, async ({ folderId }) => textResult((await bitrix('disk.folder.getchildren', { id: folderId })).result));

  server.registerTool('get_disk_file', {
    description: 'Get Bitrix24 Disk file metadata and download URL if provided by Bitrix.',
    inputSchema: z.object({ fileId: z.number().int().positive() })
  }, async ({ fileId }) => textResult((await bitrix('disk.file.get', { id: fileId })).result));
}
