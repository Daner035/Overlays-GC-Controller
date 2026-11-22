import ctypes
import sys
import pygame

# --- Configuración de ventana ---
WIDTH, HEIGHT = 340, 190
FPS_LIMIT = 120  # Lectura y refresco fluido sin bucle infinito sin pausa

pygame.init()
pygame.joystick.init()

screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("GC Input Overlay (Proto)")
font = pygame.font.SysFont("consolas", 14)
clock = pygame.time.Clock()


def set_always_on_top_windows(title: str):
    """Intenta mantener la ventana encima en Windows sin bloquear el resto."""
    if sys.platform.startswith("win"):
        hwnd = ctypes.windll.user32.FindWindowW(None, title)
        if hwnd:
            HWND_TOPMOST = -1
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            ctypes.windll.user32.SetWindowPos(
                hwnd,
                HWND_TOPMOST,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            )


set_always_on_top_windows("GC Input Overlay (Proto)")

joystick = None
if pygame.joystick.get_count() > 0:
    joystick = pygame.joystick.Joystick(0)
    joystick.init()

running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        # Permite reconectar mando si se enchufa/desenchufa
        elif event.type == pygame.JOYDEVICEADDED and joystick is None:
            joystick = pygame.joystick.Joystick(0)
            joystick.init()
        elif event.type == pygame.JOYDEVICEREMOVED:
            if pygame.joystick.get_count() == 0:
                joystick = None

    # Fondo oscuro ligero
    screen.fill((24, 26, 30))

    if joystick is None:
        msg = font.render("Conecta un mando / adaptador...", True, (235, 190, 70))
        screen.blit(msg, (20, 80))
    else:
        name = joystick.get_name()[:34]
        header = font.render(f"Mando: {name}", True, (160, 215, 255))
        screen.blit(header, (15, 12))

        # --- Stick principal (ejes 0 y 1 habitualmente) ---
        ax_x = joystick.get_axis(0) if joystick.get_numaxes() > 0 else 0.0
        ax_y = joystick.get_axis(1) if joystick.get_numaxes() > 1 else 0.0

        stick_center = (75, 105)
        stick_radius = 38
        pygame.draw.circle(screen, (60, 65, 75), stick_center, stick_radius, 2)

        knob_pos = (
            int(stick_center[0] + ax_x * (stick_radius - 8)),
            int(stick_center[1] + ax_y * (stick_radius - 8)),
        )
        pygame.draw.circle(screen, (90, 220, 140), knob_pos, 8)

        # --- Botones activos ---
        pressed = [
            str(i)
            for i in range(joystick.get_numbuttons())
            if joystick.get_button(i)
        ]
        btns_text = "Botones: " + (", ".join(pressed) if pressed else "-")
        btns_surf = font.render(btns_text, True, (230, 230, 235))
        screen.blit(btns_surf, (135, 55))

        # --- Valores numéricos del stick ---
        axes_text = f"Stick X: {ax_x:+.2f} | Y: {ax_y:+.2f}"
        axes_surf = font.render(axes_text, True, (190, 195, 205))
        screen.blit(axes_surf, (135, 90))

        # --- Hat / Cruceta ---
        hat_val = joystick.get_hat(0) if joystick.get_numhats() > 0 else (0, 0)
        hat_surf = font.render(f"D-Pad: {hat_val}", True, (190, 195, 205))
        screen.blit(hat_surf, (135, 125))

    pygame.display.flip()
    clock.tick(FPS_LIMIT)

pygame.quit()