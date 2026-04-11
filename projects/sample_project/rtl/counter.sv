// Enhanced 4-bit counter with load, direction, and overflow detection
// - Supports up/down counting
// - Load capability for setting count value
// - Overflow flag pulses on wraparound

module counter #(
    parameter int WIDTH = 4
) (
    input  logic             clk,
    input  logic             rst_n,
    input  logic             en,
    input  logic             dir,        // 0=up, 1=down
    input  logic             load_en,    // Load enable
    input  logic [WIDTH-1:0] load_val,   // Load value
    output logic [WIDTH-1:0] count,
    output logic             overflow    // Pulses on wrap
);

    logic [WIDTH-1:0] next_count;
    logic             will_overflow;

    // Compute next count value
    always_comb begin
        next_count    = count;
        will_overflow = 1'b0;

        if (load_en) begin
            next_count = load_val;
        end else if (en) begin
            if (dir) begin
                // Count down
                next_count = count - 1'b1;
                will_overflow = (count == '0);
            end else begin
                // Count up
                next_count = count + 1'b1;
                will_overflow = (count == '1);  // All 1's
            end
        end
    end

    // Sequential logic
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            count    <= '0;
            overflow <= 1'b0;
        end else begin
            count    <= next_count;
            overflow <= will_overflow && en && !load_en;
        end
    end

endmodule
