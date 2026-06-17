export function getCbThresholdState(ir) {
  const cbAlertThresholdM = Number(ir?.cb_alert_threshold_m)
  const hasCbAlertThreshold = Number.isFinite(cbAlertThresholdM) && cbAlertThresholdM > 0
  const cloudHeightM = Number(ir?.cloud_height_m ?? ir?.ir_cloud_height_m ?? 0)

  const isCbHeightAlert =
    hasCbAlertThreshold &&
    Number.isFinite(cloudHeightM) &&
    cloudHeightM >= cbAlertThresholdM

  return {
    cbAlertThresholdM,
    hasCbAlertThreshold,
    isCbHeightAlert,
  }
}

export function formatCbIrLabel({ cbAlertThresholdM, hasCbAlertThreshold, isCbHeightAlert }) {
  if (isCbHeightAlert) {
    return `🛰 CB > ${cbAlertThresholdM.toLocaleString('de-AT')}`
  }

  if (hasCbAlertThreshold) {
    return '🛰 IR-Vorläufer'
  }

  return '🛰 IR-Vorläufer (CB-Schwelle fehlt)'
}
