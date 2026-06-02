#ifndef MOD4_H
#define MOD4_H

#include <stdint.h>
#include <stdbool.h>
#include "mod3.h"

#define MAX_PLANTS               255
#define CONFIDENCE_HIGH          0.70f
#define CONFIDENCE_MEDIUM        0.50f
#define DECISION_MAX_RESCANS     2

typedef enum {
    ROBOT_STATE_IDLE = 0,
    ROBOT_STATE_NAVIGATE,
    ROBOT_STATE_APPROACH,
    ROBOT_STATE_SCAN,
    ROBOT_STATE_ANALYZE,
    ROBOT_STATE_DECIDE,
    ROBOT_STATE_ACT,
    ROBOT_STATE_LOG,
    ROBOT_STATE_PAUSED,
    ROBOT_STATE_ABORTED,
    ROBOT_STATE_ERROR
} robot_state_t;

typedef enum {
    PLANT_STATUS_HEALTHY = 0,
    PLANT_STATUS_DISEASED,
    PLANT_STATUS_WEED,
    PLANT_STATUS_UNKNOWN
} plant_status_t;

typedef enum {
    ACTION_SKIP = 0,
    ACTION_SPRAY,
    ACTION_LASER
} action_type_t;

typedef struct {
    float pan_deg;
    float tilt_deg;
} servo_angles_t;

typedef enum {
    DECISION_OK         =  0,
    DECISION_ERR_INIT   = -1,
    DECISION_ERR_STATE  = -2,
    DECISION_ERR_MODULE = -3,
    DECISION_ERR_ABORT  = -4,
    DECISION_ERR_FULL   = -5
} decision_status_t;

typedef struct {
    plant_status_t classification;
    action_type_t  decided_action;
    float          final_confidence;
    uint8_t        scan_count;
    servo_angles_t target_angles;
} decision_result_t;

typedef struct {
    uint8_t        plant_id;
    uint32_t       timestamp_ms;
    plant_status_t classification;
    action_type_t  action;
    float          confidence;
    char           diagnosis[256];
    uint32_t       inference_time_ms;
    uint8_t        scan_count;
    bool           acted;
} field_report_entry_t;

typedef struct {
    uint16_t total_plants;
    uint16_t healthy_count;
    uint16_t diseased_count;
    uint16_t weed_count;
    uint16_t unknown_count;
    uint16_t acted_count;
    uint16_t skipped_count;
} field_report_summary_t;

typedef struct {
    float    conf_high;
    float    conf_medium;
    uint8_t  max_rescans;
    uint32_t pump_duration_ms;
    uint32_t laser_duration_ms;
} mission_config_t;

typedef void (*decision_state_cb_t)(robot_state_t new_state,
                                    uint8_t plant_id,
                                    const decision_result_t *result);

decision_status_t decision_init(const mission_config_t *config);
decision_status_t decision_shutdown(void);
decision_status_t decision_start_mission(void);
decision_status_t decision_pause_mission(void);
decision_status_t decision_resume_mission(void);
decision_status_t decision_abort_mission(void);
robot_state_t     decision_get_state(void);
decision_status_t decision_register_state_callback(decision_state_cb_t cb);
decision_status_t decision_evaluate(const vlm_result_t *vlm_result,
                                    uint8_t scan_count,
                                    decision_result_t *result);
decision_status_t decision_add_report_entry(const field_report_entry_t *entry);
decision_status_t decision_get_report_summary(field_report_summary_t *summary);
decision_status_t decision_get_report_entry(uint8_t plant_id,
                                            field_report_entry_t *entry);
decision_status_t decision_clear_report(void);

#endif /* MOD4_H */
