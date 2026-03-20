// Testbench for counter.sv
// LibreRun compliant: wave dumping gated via $test$plusargs("waves")

`timescale 1ns/1ps

module tb_counter;

    // -------------------------------------------------------------------------
    // Parameters
    // -------------------------------------------------------------------------
    localparam int WIDTH     = 4;
    localparam int CLK_HALF  = 5;   // 10ns clock period

    // -------------------------------------------------------------------------
    // DUT signals
    // -------------------------------------------------------------------------
    logic             clk;
    logic             rst_n;
    logic             en;
    logic [WIDTH-1:0] count;

    // -------------------------------------------------------------------------
    // DUT instantiation
    // -------------------------------------------------------------------------
    counter #(
        .WIDTH(WIDTH)
    ) dut (
        .clk   (clk),
        .rst_n (rst_n),
        .en    (en),
        .count (count)
    );

    // -------------------------------------------------------------------------
    // Clock generation
    // -------------------------------------------------------------------------
    initial clk = 0;
    always #CLK_HALF clk = ~clk;

    // -------------------------------------------------------------------------
    // Waveform dumping — gated by +waves plusarg (LibreRun controlled)
    // -------------------------------------------------------------------------
    initial begin
        if ($test$plusargs("waves")) begin
            $dumpfile("waves.fst");
            $dumpvars(0, tb_counter);
            $display("[TB] Waveform dumping enabled -> waves.fst");
        end
    end

    // -------------------------------------------------------------------------
    // Stimulus + checking
    // -------------------------------------------------------------------------
    initial begin
        // Init
        rst_n = 0;
        en    = 0;

        // Hold reset for 3 cycles
        repeat(3) @(posedge clk);
        rst_n = 1;

        // Check count is 0 after reset
        @(negedge clk);
        if (count !== '0)
            $error("[TB] FAIL: Expected count=0 after reset, got count=%0d", count);
        else
            $display("[TB] PASS: count=0 after reset");

        // Enable counting, run for 18 cycles (wraps around once at 16)
        en = 1;
        repeat(18) begin
            @(posedge clk);
            $display("[TB] count = %0d", count);
        end

        // Disable enable, check count holds
        en = 0;
        @(posedge clk);
        @(negedge clk);
        begin
            logic [WIDTH-1:0] held;
            held = count;
            @(posedge clk);
            @(negedge clk);
            if (count !== held)
                $error("[TB] FAIL: count changed while en=0 (was %0d, now %0d)", held, count);
            else
                $display("[TB] PASS: count held at %0d while en=0", count);
        end

        // Re-enable, count a few more
        en = 1;
        repeat(4) @(posedge clk);

        // Assert reset mid-run
        rst_n = 0;
        @(posedge clk);
        @(negedge clk);
        if (count !== '0)
            $error("[TB] FAIL: Expected count=0 after mid-run reset, got %0d", count);
        else
            $display("[TB] PASS: count=0 after mid-run reset");

        $display("[TB] Simulation complete.");
        $finish;
    end

endmodule
