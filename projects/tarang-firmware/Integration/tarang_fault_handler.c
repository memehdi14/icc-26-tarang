/***************************************************************************//**
 * @file tarang_fault_handler.c
 * @brief Cortex-M33 HardFault handler — prints crash diagnostics to VCOM.
 *
 * When a HardFault occurs (stack overflow, null pointer, bad memory access),
 * this handler prints the faulting PC, LR, and register state to VCOM serial
 * so you can see WHERE the crash happened instead of a silent freeze.
 *
 * Target: EFR32MG26B510F3200IM48 (Cortex-M33)
 ******************************************************************************/

#include <stdint.h>
#include <stdio.h>

/* Override the weak default HardFault_Handler from startup code */
void HardFault_Handler(void) __attribute__((naked));

void HardFault_Handler(void)
{
  __asm volatile(
    /* Check which stack pointer was in use (MSP or PSP) */
    "tst lr, #4           \n"
    "ite eq               \n"
    "mrseq r0, msp        \n"
    "mrsne r0, psp        \n"
    "b hard_fault_handler_c \n"
  );
}

/* This function receives the stacked frame pointer */
void hard_fault_handler_c(uint32_t *hardfault_args)
    __attribute__((used));

void hard_fault_handler_c(uint32_t *hardfault_args)
{
  volatile uint32_t stacked_r0  = hardfault_args[0];
  volatile uint32_t stacked_r1  = hardfault_args[1];
  volatile uint32_t stacked_r2  = hardfault_args[2];
  volatile uint32_t stacked_r3  = hardfault_args[3];
  volatile uint32_t stacked_r12 = hardfault_args[4];
  volatile uint32_t stacked_lr  = hardfault_args[5];
  volatile uint32_t stacked_pc  = hardfault_args[6];
  volatile uint32_t stacked_psr = hardfault_args[7];

  /* Suppress unused warnings */
  (void)stacked_r0;
  (void)stacked_r1;
  (void)stacked_r2;
  (void)stacked_r3;
  (void)stacked_r12;

  printf("\r\n\r\n");
  printf("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\r\n");
  printf("!!! HARD FAULT — BOARD CRASHED !!!\r\n");
  printf("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\r\n");
  printf("  PC  = 0x%08lX  <-- crashed HERE\r\n", (unsigned long)stacked_pc);
  printf("  LR  = 0x%08lX  <-- called FROM\r\n", (unsigned long)stacked_lr);
  printf("  PSR = 0x%08lX\r\n", (unsigned long)stacked_psr);
  printf("  R0  = 0x%08lX  R1 = 0x%08lX\r\n",
         (unsigned long)stacked_r0, (unsigned long)stacked_r1);
  printf("  R2  = 0x%08lX  R3 = 0x%08lX\r\n",
         (unsigned long)stacked_r2, (unsigned long)stacked_r3);
  printf("  R12 = 0x%08lX\r\n", (unsigned long)stacked_r12);

  /* Check stack pointer against limits */
  extern uint32_t __StackLimit;
  extern uint32_t __StackTop;
  uint32_t sp = (uint32_t)hardfault_args;
  printf("  SP  = 0x%08lX\r\n", (unsigned long)sp);
  printf("  Stack: limit=0x%08lX top=0x%08lX\r\n",
         (unsigned long)&__StackLimit,
         (unsigned long)&__StackTop);

  if (sp < (uint32_t)&__StackLimit) {
    printf("  >>> STACK OVERFLOW DETECTED <<<\r\n");
  }

  printf("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\r\n");
  printf("System halted. Reset the board.\r\n");

  /* Halt in infinite loop so the serial output stays visible */
  while (1) { }
}
