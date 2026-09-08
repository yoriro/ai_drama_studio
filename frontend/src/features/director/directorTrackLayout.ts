const MIN_SHOT_COLUMN_WIDTH = 192;
const TRACK_GAP = 8;

export function calculateDirectorTrackContentWidth(
  durationEstimates: readonly number[],
): number {
  if (durationEstimates.length === 0) {
    return 0;
  }

  const totalDuration = durationEstimates.reduce(
    (sum, duration) => sum + duration,
    0,
  );
  const shortestDuration = Math.min(...durationEstimates);
  return Math.ceil(
    (MIN_SHOT_COLUMN_WIDTH * totalDuration) / shortestDuration +
      TRACK_GAP * (durationEstimates.length - 1),
  );
}
