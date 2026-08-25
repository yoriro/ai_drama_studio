import { requestJson, requestNoContent } from "./client";

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
  seed: number | null;
  source: AssetImageSource;
  is_current: boolean;
  created_at: string;
}

interface CurrentImagePatch {
  image_id: number;
}

const jsonHeaders = { "Content-Type": "application/json" };

export function listAssets(projectId: number): Promise<Asset[]> {
  return requestJson<Asset[]>(`/projects/${projectId}/assets`);
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
  if (!Number.isInteger(imageId) || imageId <= 0) {
    throw new Error("imageId must be a positive integer");
  }
  return `/media/asset-images/${imageId}`;
}
