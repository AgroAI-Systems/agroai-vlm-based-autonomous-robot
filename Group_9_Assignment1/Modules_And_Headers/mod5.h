#ifndef MOD5_H
#define MOD5_H

#include <stdint.h>
#include <stdbool.h>
#include "mod2.h"
#include "mod4.h"

#define DASHBOARD_DEFAULT_PORT      8080
#define DASHBOARD_WS_PATH           "/ws"
#define DASHBOARD_STREAM_PATH       "/stream"
#define DASHBOARD_DB_FILENAME       "field_report.db"
#define DASHBOARD_MAX_WS_CLIENTS    8

typedef enum {
    DASHBOARD_OK              =  0,
    DASHBOARD_ERR_INIT        = -1,
    DASHBOARD_ERR_PORT        = -2,
    DASHBOARD_ERR_DB          = -3,
    DASHBOARD_ERR_STREAM      = -4,
    DASHBOARD_ERR_NOT_RUNNING = -5
} dashboard_error_t;

typedef struct {
    robot_state_t current_state;
    uint8_t       current_plant_id;
    bool          mission_active;
    float         battery_percent;
    uint32_t      uptime_ms;
} dashboard_runtime_status_t;

typedef struct {
    uint16_t    port;
    const char *web_root;
    const char *db_path;
    bool        enable_stream;
} dashboard_config_t;

typedef struct {
    plant_status_t status_filter;
    uint8_t        limit;
    bool           newest_first;
} db_query_filter_t;

typedef void (*dashboard_command_cb_t)(const char *command);

dashboard_error_t dashboard_init(const dashboard_config_t *config);
dashboard_error_t dashboard_start(void);
dashboard_error_t dashboard_stop(void);
bool              dashboard_is_running(void);
dashboard_error_t dashboard_push_status(const dashboard_runtime_status_t *status);
dashboard_error_t dashboard_push_vlm_result(uint8_t plant_id,
                                            const vlm_result_t *result);
dashboard_error_t dashboard_push_frame(const camera_frame_t *frame,
                                       const bbox_t *overlay_boxes,
                                       uint8_t box_count);
dashboard_error_t dashboard_db_log_entry(const field_report_entry_t *entry);
dashboard_error_t dashboard_db_get_entries(const db_query_filter_t *filter,
                                           field_report_entry_t *entries,
                                           uint8_t max_entries,
                                           uint8_t *out_count);
dashboard_error_t dashboard_db_get_summary(field_report_summary_t *summary);
dashboard_error_t dashboard_db_clear(void);
dashboard_error_t dashboard_register_command_callback(dashboard_command_cb_t cb);

#endif /* MOD5_H */
