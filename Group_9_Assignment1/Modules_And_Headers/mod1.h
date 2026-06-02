#ifndef MOD1_H
#define MOD1_H

#include <stdint.h>
#include <stdbool.h>

#define PATHING_IR_SENSOR_COUNT         5
#define PATHING_IR_PIN_0                6
#define PATHING_IR_PIN_1                13
#define PATHING_IR_PIN_2                19
#define PATHING_IR_PIN_3                26
#define PATHING_IR_PIN_4                21

#define PATHING_MOTOR_L_PWM_PIN         12
#define PATHING_MOTOR_L_IN1_PIN         23
#define PATHING_MOTOR_L_IN2_PIN         24
#define PATHING_MOTOR_R_PWM_PIN         13
#define PATHING_MOTOR_R_IN1_PIN         20
#define PATHING_MOTOR_R_IN2_PIN         16

#define PATHING_MOTOR_PWM_FREQ_HZ       1000
#define PATHING_MOTOR_DUTY_MIN          0
#define PATHING_MOTOR_DUTY_MAX          100
#define PATHING_MOTOR_BASE_SPEED        60

#define PATHING_PID_KP_DEFAULT          0.35f
#define PATHING_PID_KI_DEFAULT          0.0f
#define PATHING_PID_KD_DEFAULT          0.10f
#define PATHING_PID_LOOP_RATE_HZ        100
#define PATHING_PID_LOOP_PERIOD_MS      10

#define PATHING_PLANT_MARKER_PATTERN    0x1F

typedef enum {
    PATHING_OK              =  0,
    PATHING_ERR_INIT        = -1,
    PATHING_ERR_INVALID_ARG = -2,
    PATHING_ERR_MOTOR       = -3,
    PATHING_ERR_IR          = -4,
    PATHING_ERR_NOT_RUNNING = -5
} pathing_status_t;

typedef enum {
    PATHING_STATE_IDLE      = 0,
    PATHING_STATE_NAVIGATE  = 1,
    PATHING_STATE_STOPPING  = 2,
    PATHING_STATE_STOPPED   = 3,
    PATHING_STATE_ERROR     = 4
} pathing_state_t;

typedef struct {
    uint8_t  mask;
    uint8_t  raw[PATHING_IR_SENSOR_COUNT];
    uint32_t timestamp_ms;
} pathing_ir_reading_t;

typedef struct {
    float kp;
    float ki;
    float kd;
    float error;
    float prev_error;
    float integral;
    float output;
} pathing_pid_state_t;

typedef struct {
    uint8_t duty;
    bool    forward;
} pathing_motor_cmd_t;

typedef struct {
    uint8_t ir_pins[PATHING_IR_SENSOR_COUNT];
    uint8_t motor_l_pwm;
    uint8_t motor_l_in1;
    uint8_t motor_l_in2;
    uint8_t motor_r_pwm;
    uint8_t motor_r_in1;
    uint8_t motor_r_in2;
    float   kp;
    float   ki;
    float   kd;
    uint8_t base_speed;
} pathing_config_t;

typedef void (*pathing_plant_detected_cb_t)(uint32_t timestamp_ms);
typedef void (*pathing_state_change_cb_t)(pathing_state_t new_state);

pathing_status_t pathing_init(const pathing_config_t *cfg,
                              pathing_plant_detected_cb_t on_plant,
                              pathing_state_change_cb_t on_state);
pathing_status_t pathing_start(void);
pathing_status_t pathing_resume(void);
pathing_status_t pathing_stop(void);
pathing_status_t pathing_read_ir(pathing_ir_reading_t *out);
pathing_status_t pathing_set_motors(const pathing_motor_cmd_t *left,
                                    const pathing_motor_cmd_t *right);
pathing_status_t pathing_get_pid_state(pathing_pid_state_t *out);
pathing_status_t pathing_set_pid_gains(float kp, float ki, float kd);
pathing_state_t  pathing_get_state(void);
pathing_status_t pathing_deinit(void);

#endif /* MOD1_H */
