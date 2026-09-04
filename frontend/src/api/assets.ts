import {
  ApiProtocolError,
  protocolError,
  requestJson,
  requestNoContent,
  requireEnum,
  requireObjectWithKeys,
  requirePositiveSafeInteger,
  requireString,
} from "./client";

export type AssetType = "character" | "scene";
export type AssetSource = "generated" | "manual";
export type AssetImageSource = "generated" | "uploaded";

export interface Asset {
  id: number;
  project_id: number;
  type: AssetType;
  name: string;
  description: string;
  source: AssetSource;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface AssetCreate {
  type: AssetType;
  name: string;
  description: string;
}

export interface AssetPatch {
  name?: string;
  description?: string;
}

export interface AssetImage {
  id: number;
  asset_id: number;
  sha256: string;
  seed: string | null;
  source: AssetImageSource;
  is_current: boolean;
  created_at: string;
  built_prompt?: string | null;
  input_snapshot?: Record<string, unknown> | null;
}

export interface GenerateAssetImageRequest {
  user_note: string | null;
  request_id?: string | null;
}

export interface GenerateAssetImageResponse {
  task_id: number;
}

interface CurrentImagePatch {
  image_id: number;
}

const jsonHeaders = { "Content-Type": "application/json" };

export function parseAssetResponse(value: unknown, status = 200): Asset {
  const record = requireObjectWithKeys(
    value,
    [
      "id",
      "project_id",
      "type",
      "name",
      "description",
      "source",
      "revision",
      "created_at",
      "updated_at",
    ],
    [],
    status,
    "Asset response",
  );
  requirePositiveSafeInteger(record.id, "Asset.id", status);
  requirePositiveSafeInteger(record.project_id, "Asset.project_id", status);
  requireEnum(record.type, ["character", "scene"] as const, "Asset.type", status);
  requireString(record.name, status, "Asset.name");
  requireString(record.description, status, "Asset.description");
  requireEnum(record.source, ["generated", "manual"] as const, "Asset.source", status);
  requirePositiveSafeInteger(record.revision, "Asset.revision", status);
  requireString(record.created_at, status, "Asset.created_at");
  requireString(record.updated_at, status, "Asset.updated_at");
  return record as unknown as Asset;
}

export function parseAssetListResponse(
  value: unknown,
  status = 200,
): Asset[] {
  if (!Array.isArray(value)) {
    return protocolError(status, "Asset list response must be an array");
  }
  return value.map((item) => parseAssetResponse(item, status));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(
  value: Record<string, unknown>,
  keys: readonly string[],
): boolean {
  const actualKeys = Object.keys(value);
  return (
    actualKeys.length === keys.length &&
    keys.every((key) => Object.prototype.hasOwnProperty.call(value, key))
  );
}

function isGenerateAssetImageResponse(
  value: unknown,
): value is GenerateAssetImageResponse {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["task_id"]) &&
    typeof value.task_id === "number" &&
    Number.isInteger(value.task_id) &&
    value.task_id > 0
  );
}

export function listAssets(projectId: number): Promise<Asset[]> {
  const id = requirePositiveSafeInteger(projectId, "projectId");
  return requestJson<Asset[]>(
    `/projects/${id}/assets`,
    undefined,
    parseAssetListResponse,
  );
}

export function createAsset(
  projectId: number,
  input: AssetCreate,
): Promise<Asset> {
  return requestJson<Asset>(`/projects/${projectId}/assets`, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export async function generateAssetImage(
  assetId: number,
  input: GenerateAssetImageRequest,
): Promise<GenerateAssetImageResponse> {
  const payload = await requestJson<unknown>(
    `/assets/${assetId}/generate-image`,
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(input),
    },
  );
  if (!isGenerateAssetImageResponse(payload)) {
    throw new ApiProtocolError(
      202,
      "Generate-image response did not match its schema",
    );
  }
  return payload;
}

export function getAsset(id: number): Promise<Asset> {
  return requestJson<Asset>(`/assets/${id}`);
}

export function updateAsset(id: number, input: AssetPatch): Promise<Asset> {
  return requestJson<Asset>(`/assets/${id}`, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export function deleteAsset(id: number): Promise<void> {
  return requestNoContent(`/assets/${id}`, { method: "DELETE" });
}

export function listAssetImages(assetId: number): Promise<AssetImage[]> {
  return requestJson<AssetImage[]>(`/assets/${assetId}/images`);
}

export function uploadAssetImage(
  assetId: number,
  file: File,
): Promise<AssetImage> {
  const formData = new FormData();
  formData.append("file", file);
  return requestJson<AssetImage>(`/assets/${assetId}/images`, {
    method: "POST",
    body: formData,
  });
}

export function setCurrentAssetImage(
  assetId: number,
  imageId: number,
): Promise<AssetImage> {
  const input: CurrentImagePatch = { image_id: imageId };
  return requestJson<AssetImage>(`/assets/${assetId}/current-image`, {
    method: "PUT",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export function deleteAssetImage(imageId: number): Promise<void> {
  return requestNoContent(`/asset-images/${imageId}`, { method: "DELETE" });
}

export function getAssetImageMediaUrl(imageId: number): string {
  const id = requirePositiveSafeInteger(imageId, "imageId");
  return `/media/asset-images/${id}`;
}
